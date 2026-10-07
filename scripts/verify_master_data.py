"""Read-only release snapshot: compare record hashes, balances and accounting totals."""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from bson import json_util
from db import db


def canonical(value):
    return json_util.dumps(value, sort_keys=True)


async def main():
    baseline = json.loads(Path(sys.argv[1]).read_text())
    current = {"collections": {}, "totals": {}}
    for name in await db.list_collection_names():
        rows = await db[name].find({}).to_list(None)
        current["collections"][name] = {
            str(row["_id"]): hashlib.sha256(canonical(row).encode()).hexdigest()
            for row in rows
        }
    for name in ("bot_users", "store_customers"):
        current["totals"][name] = await db[name].aggregate([{"$group": {
            "_id": None, "idr": {"$sum": "$balance_idr"}, "usd": {"$sum": "$balance_usd"}
        }}]).to_list(None)
    for name, field in (("purchases", "total"), ("deposits", "credited_amount")):
        current["totals"][name] = await db[name].aggregate([{"$group": {
            "_id": {"currency": "$currency", "status": "$status"},
            "amount": {"$sum": "$" + field}, "count": {"$sum": 1}
        }}]).to_list(None)
    settings = await db.settings.find_one({"_id": "main"}) or {}
    current["stats_reset_at"] = settings.get("stats_reset_at")
    changes = {}
    for name, before in baseline["collections"].items():
        after = current["collections"].get(name, {})
        changes[name] = {"before": len(before), "after": len(after),
            "missing": len(before.keys() - after.keys()),
            "new": len(after.keys() - before.keys()),
            "changed": sum(before[key] != after[key] for key in before.keys() & after.keys())}
    financial = {name: sorted(map(canonical, before)) == sorted(map(canonical, current["totals"][name]))
                 for name, before in baseline["totals"].items()}
    report = {"changes": changes, "financial_totals_unchanged": financial,
              "stats_cutoff_unchanged": baseline["stats_reset_at"] == current["stats_reset_at"]}
    current["verification"] = report
    descriptor = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(canonical(current))
    print(json.dumps(report, indent=2))
    persistent = ("products", "product_catalogs", "inventory_items", "purchases", "deposits",
                  "bot_users", "store_customers", "gopay_payments", "balance_adjustments")
    assert all(changes.get(name, {}).get("missing", 0) == 0 for name in persistent), "Existing records missing; investigate."
    assert report["stats_cutoff_unchanged"], "Statistics cutoff changed; investigate."


asyncio.run(main())
