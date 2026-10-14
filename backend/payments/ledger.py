"""Standalone-Mongo settlement journal. Events + version share one atomic CAS.

The immutable journal is authoritative. settlement_entries is only a repairable
projection. No balance cached outside this document authorizes a payout.
"""
from uuid import uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from .models import now, money

BUCKETS = ("pending", "clearing", "available", "reserved", "paid_out", "liability")

def balances(events):
    result = dict.fromkeys(BUCKETS, 0)
    for event in events:
        for key, value in event.get("deltas", {}).items():
            result[key] += value
    return result

class Ledger:
    def __init__(self, database, tenant_id):
        self.db, self.tenant = database, tenant_id

    async def get(self):
        try:
            await self.db.settlement_accounts.update_one({"_id": self.tenant}, {"$setOnInsert": {"version": 0, "events": []}}, upsert=True)
        except DuplicateKeyError:
            pass  # A concurrent first credit created the same account.
        doc = await self.db.settlement_accounts.find_one({"_id": self.tenant})
        await self.project(doc)
        return doc

    async def project(self, doc):
        for entry in doc["events"]:
            try:
                await self.db.settlement_entries.update_one({"_id": entry["_id"]}, {"$setOnInsert": entry}, upsert=True)
            except DuplicateKeyError:
                pass

    async def append(self, reference, intent, build):
        for _ in range(50):
            account = await self.get()
            prior = [e for e in account["events"] if e["reference"] == reference]
            if prior:
                if any(e["intent"] != intent for e in prior):
                    raise CommerceError("Settlement idempotency conflict")
                return prior
            if len(account["events"]) >= 10000:
                raise FulfillmentUnavailable("Settlement journal archival required")
            additions = build(account["events"], balances(account["events"]))
            events = [{"_id": str(uuid5(NAMESPACE_URL, f"settlement:{self.db.name}:{self.tenant}:{reference}:{i}")), "tenant_id": self.tenant, "reference": reference, "idempotency_key": reference, "intent": intent, "currency": "IDR", "created_at": now(), **e} for i, e in enumerate(additions)]
            values = balances(account["events"] + events)
            if any(v < 0 for v in values.values()):
                raise CommerceError("Invalid settlement balance")
            changed = await self.db.settlement_accounts.update_one({"_id": self.tenant, "version": account["version"]}, {"$inc": {"version": 1}, "$push": {"events": {"$each": events}}})
            if changed.modified_count:
                await self.project(await self.db.settlement_accounts.find_one({"_id": self.tenant}))
                return events
        raise FulfillmentUnavailable("Settlement changed concurrently; retry")

    async def credit(self, payment):
        if payment["payment_mode"] != "platform_settlement":
            return []
        gross = money(payment["amount"])
        gateway, platform = money(payment.get("gateway_fee", 0)), money(payment.get("platform_fee", 0))
        if gross < gateway + platform:
            raise CommerceError("Fees exceed payment")
        intent = {"gross": gross, "gateway": gateway, "platform": platform, "payment_id": payment["_id"]}
        def build(events, values):
            common = {"payment_id": payment["_id"], "order_id": payment["order_id"], "environment": payment["environment"], "state": "pending", "available_at": payment.get("available_at")}
            return [{**common, "type": kind, "amount": value, "deltas": delta} for kind, value, delta in [("PAYMENT_GROSS", gross, {}), ("GATEWAY_FEE", gateway, {}), ("PLATFORM_FEE", platform, {}), ("NET_PENDING", gross - gateway - platform, {"pending": gross - gateway - platform})]]
        return await self.append("payment:" + payment["_id"], intent, build)

    async def advance(self, payment, target):
        if target not in {"clearing", "available"}:
            raise CommerceError("Invalid settlement state")
        # Configured dates, rather than an invented production T+N.
        deadline = payment["clearing_at"] if target == "clearing" else payment["available_at"]
        if deadline.replace(tzinfo=now().tzinfo) > now():
            raise CommerceError("Settlement delay has not elapsed")
        pid = payment["_id"]
        def build(events, values):
            source = "pending" if target == "clearing" else "clearing"
            prefix = "payment:" + pid if source == "pending" else "clearing:" + pid
            prior = [e for e in events if e["reference"] == prefix]
            if not prior:
                raise CommerceError("Previous settlement stage required")
            credit = next((e for e in events if e["reference"] == "payment:" + pid and e["type"] == "NET_PENDING"), None)
            # Each payment moves only its remaining balance. A reversal for
            # another payment can never consume this payment's pending funds.
            value = sum(e.get("deltas", {}).get(source, 0) for e in events if e.get("payment_id") == pid)
            return [{"type": "NET_CLEARING" if target == "clearing" else "NET_AVAILABLE", "amount": value, "state": target, "payment_id": pid, "deltas": {source: -value, target: value}}]
        return await self.append(target + ":" + pid, {"payment_id": pid, "stage": target}, build)

    async def reverse(self, payment, refund):
        if payment["payment_mode"] != "platform_settlement":
            return []
        def build(events, values):
            if not any(e["reference"] == "payment:" + payment["_id"] for e in events):
                raise CommerceError("Settlement credit required before reversal")
            remaining = refund["amount"]
            delta = {}
            for bucket in ("pending", "clearing", "available"):
                eligible = values[bucket] if bucket == "available" else max(0, sum(e.get("deltas", {}).get(bucket, 0) for e in events if e.get("payment_id") == payment["_id"]))
                used = min(eligible, remaining)
                delta[bucket] = -used
                remaining -= used
            delta["liability"] = remaining
            return [{"type": "REFUND_REVERSAL", "amount": refund["amount"], "payment_id": payment["_id"], "refund_id": refund["_id"], "state": "reversed", "deltas": delta}]
        return await self.append("refund:" + refund["_id"], {"payment_id": payment["_id"], "amount": refund["amount"]}, build)

    async def request_payout(self, key, amount, bank):
        amount = money(amount, positive=True)
        if bank.get("verification_status") != "mock_verified":
            raise CommerceError("Verified mock bank required; live payouts disabled")
        def build(events, values):
            if amount > values["available"] - values["liability"]:
                raise CommerceError("Insufficient available settlement")
            if any(e.get("environment") != "mock" for e in events if e["type"] == "PAYMENT_GROSS"):
                raise CommerceError("Live/sandbox funds cannot enter simulated payout")
            return [{"type": "PAYOUT_RESERVE", "amount": amount, "payout_id": key, "state": "requested", "bank_snapshot": bank, "deltas": {"available": -amount, "reserved": amount}}]
        return await self.append("payout:" + key, {"amount": amount, "bank_version": bank["_id"]}, build)

    async def payout_transition(self, key, state):
        transitions = {"requested": {"reviewing", "cancelled", "rejected"}, "reviewing": {"processing", "cancelled", "rejected"}, "processing": {"paid", "failed"}}
        def build(events, values):
            history = [e for e in events if e.get("payout_id") == key]
            if not history:
                raise CommerceError("Payout not found")
            current, amount = history[-1]["state"], history[0]["amount"]
            if state not in transitions.get(current, set()):
                raise CommerceError("Invalid payout transition")
            delta = {"reserved": -amount, "paid_out": amount} if state == "paid" else {"reserved": -amount, "available": amount} if state in {"failed", "rejected", "cancelled"} else {}
            return [{"type": "PAYOUT" if state == "paid" else "PAYOUT_STATE", "payout_id": key, "amount": amount, "state": state, "coverage": "MOCKED", "deltas": delta}]
        return await self.append(f"payout:{key}:{state}", {"payout_id": key, "state": state}, build)
