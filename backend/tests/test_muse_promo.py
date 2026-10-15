import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from db import db, get_settings
import muse_promo
import bot

@pytest.fixture(autouse=True)
def clean_db():
    async def reset():
        for coll in ["settings", "bot_users", "muse_claims", "muse_active_claims", "counters", "gopay_payments", "deposits"]:
            await db[coll].delete_many({})
        await db.settings.insert_one({"_id": "main", "admin_telegram_id": "999"})
    asyncio.run(reset())

async def test_01_feature_enabled_disabled():
    cfg = await muse_promo.config()
    assert cfg["enabled"] is True
    await db.settings.update_one({"_id": "main"}, {"$set": {"promo_muse.enabled": False}})
    cfg = await muse_promo.config()
    assert cfg["enabled"] is False

async def test_02_admin_editable_base_price():
    await db.settings.update_one({"_id": "main"}, {"$set": {"promo_muse.base_price_idr": 25000}})
    cfg = await muse_promo.config()
    assert cfg["base_price_idr"] == 25000

async def test_03_04_05_06_formula_calculation_and_sequence():
    cfg = await muse_promo.config()
    q1 = muse_promo.quote(cfg, 1)
    assert q1["base_price_idr"] == 15000
    assert q1["percentage_fee_idr"] == 105
    assert q1["admin_fee_idr"] == 250
    assert q1["unique_code_idr"] == 1
    assert q1["final_amount_idr"] == 15356
    assert isinstance(q1["final_amount_idr"], int)
    q2 = muse_promo.quote(cfg, 2)
    assert q2["final_amount_idr"] == 15357
    assert isinstance(q2["final_amount_idr"], int)

async def test_07_08_unique_sequence_allocation_atomic_and_concurrent():
    codes = await asyncio.gather(*(muse_promo.allocate_unique_code() for _ in range(50)))
    assert len(codes) == 50
    assert len(set(codes)) == 50
    assert set(codes) == set(range(1, 51))

async def test_09_10_referral_collected_before_qris(monkeypatch):
    user = {"telegram_id": 12345, "username": "buyer"}
    claim = await muse_promo.create_claim(user)
    assert claim["status"] == "AWAITING_CODE"
    assert "referral_code" not in claim
    saved = await muse_promo.save_referral(claim["claim_id"], user["telegram_id"], "musepromo123")
    assert saved["status"] == "AWAITING_CONFIRMATION"
    assert saved["referral_code"] == "MUSEPROMO123"

    async def fake_gopay(claim_doc, pricing):
        return {
            "payment_id": "pay-1",
            "payment_amount": pricing["final_amount_idr"],
            "image": b"fake",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "expires_in_minutes": 5,
        }
    monkeypatch.setattr("gopay_provider.create_gopay_muse_payment", fake_gopay)
    updated, payment = await muse_promo.create_payment(claim["claim_id"], user["telegram_id"])
    assert updated["status"] == "PAYMENT_PENDING"
    assert updated["payment_id"] == "pay-1"

async def test_11_12_owner_card_and_processing_not_sent_before_payment(monkeypatch):
    sent = []
    async def mock_send(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))
        return {"ok": True, "result": {"message_id": len(sent)}}
    monkeypatch.setattr("tgapi.send_message", mock_send)
    user = {"telegram_id": 111, "username": "user1"}
    claim = await muse_promo.create_claim(user)
    await muse_promo.save_referral(claim["claim_id"], 111, "REF1")
    assert len(sent) == 0

async def test_13_14_15_payment_detection_sends_exactly_one_owner_card(monkeypatch):
    sent = []
    async def mock_send(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))
        return {"ok": True, "result": {"message_id": 100 + len(sent)}}
    monkeypatch.setattr("tgapi.send_message", mock_send)
    user = {"telegram_id": 222, "username": "validuser"}
    claim = await muse_promo.create_claim(user)
    await muse_promo.save_referral(claim["claim_id"], 222, "REF2")
    await db.muse_claims.update_one({"claim_id": claim["claim_id"]}, {"$set": {"status": "PAYMENT_PENDING", "payment_id": "p-222"}})

    payment = {"_id": "p-222"}
    first = await muse_promo.confirm_verified_payment(payment, "TX999")
    assert first is True
    assert len(sent) == 2  # user processing + owner card
    user_msg = sent[0]
    owner_msg = sent[1]
    assert user_msg[0] == 222
    assert "sedang diproses admin" in user_msg[1]
    assert owner_msg[0] == 999
    assert "@validuser" in owner_msg[1]
    assert "222" in owner_msg[1]
    assert "REF2" in owner_msg[1]
    # duplicate payment event
    second = await muse_promo.confirm_verified_payment(payment, "TX999")
    assert second is False
    assert len(sent) == 2

async def test_16_17_18_19_20_21_22_claim_scoped_actions_and_concurrency(monkeypatch):
    sent = []
    edited = []
    async def mock_send(chat_id, text, kb=None):
        sent.append((chat_id, text))
        return {"ok": True}
    async def mock_edit(chat_id, msg_id, text, kb=None):
        edited.append((chat_id, msg_id, text))
        return {"ok": True}
    monkeypatch.setattr("tgapi.send_message", mock_send)
    monkeypatch.setattr("tgapi.edit_message", mock_edit)

    # create two separate claims A and B
    userA = {"telegram_id": 101, "username": "userA"}
    claimA = await muse_promo.create_claim(userA)
    await db.muse_claims.update_one({"claim_id": claimA["claim_id"]}, {"$set": {"status": "WAITING_OWNER", "referral_code": "CODEA"}})

    userB = {"telegram_id": 102, "username": "userB"}
    claimB = await muse_promo.create_claim(userB)
    await db.muse_claims.update_one({"claim_id": claimB["claim_id"]}, {"$set": {"status": "WAITING_OWNER", "referral_code": "CODEB"}})

    # ordinary user cannot execute owner action
    unauth = await muse_promo.owner_action(claimA["claim_id"], 101, "done")
    assert unauth is None

    # simultaneous Reject vs Done on claimA
    res1, res2 = await asyncio.gather(
        muse_promo.owner_action(claimA["claim_id"], 999, "reject"),
        muse_promo.owner_action(claimA["claim_id"], 999, "done"),
    )
    assert (res1 is not None and res2 is None) or (res1 is None and res2 is not None)
    winner = res1 or res2
    await muse_promo.finish_owner_action(winner)

    # verify claimB was completely untouched
    docB = await db.muse_claims.find_one({"claim_id": claimB["claim_id"]})
    assert docB["status"] == "WAITING_OWNER"

    # double click on claimA is no-op
    retry = await muse_promo.owner_action(claimA["claim_id"], 999, "done")
    assert retry is None

    # finish claimB as done
    resB = await muse_promo.owner_action(claimB["claim_id"], 999, "done")
    assert resB is not None
    await muse_promo.finish_owner_action(resB)
    docB = await db.muse_claims.find_one({"claim_id": claimB["claim_id"]})
    assert docB["status"] == "DONE"

async def test_24_25_correct_user_notifications(monkeypatch):
    sent = []
    async def mock_send(chat_id, text, kb=None):
        sent.append((chat_id, text))
        return {"ok": True}
    monkeypatch.setattr("tgapi.send_message", mock_send)
    monkeypatch.setattr("tgapi.edit_message", lambda *args, **kwargs: asyncio.sleep(0, {"ok": True}))

    # reject notification
    claim_rej = await muse_promo.create_claim({"telegram_id": 301, "username": "rejuser"})
    await db.muse_claims.update_one({"claim_id": claim_rej["claim_id"]}, {"$set": {"status": "WAITING_OWNER", "referral_code": "REJ"}})
    act_rej = await muse_promo.owner_action(claim_rej["claim_id"], 999, "reject")
    await muse_promo.finish_owner_action(act_rej)
    assert any(c == 301 and "sudah pernah claim promo" in t for c, t in sent)

    # done notification
    claim_done = await muse_promo.create_claim({"telegram_id": 302, "username": "doneuser"})
    await db.muse_claims.update_one({"claim_id": claim_done["claim_id"]}, {"$set": {"status": "WAITING_OWNER", "referral_code": "DONE"}})
    act_done = await muse_promo.owner_action(claim_done["claim_id"], 999, "done")
    await muse_promo.finish_owner_action(act_done)
    assert any(c == 302 and "selesai diproses" in t for c, t in sent)

async def test_27_unpaid_expired_payment_never_reaches_owner():
    user = {"telegram_id": 401, "username": "expuser"}
    claim = await muse_promo.create_claim(user)
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await db.muse_claims.update_one({"claim_id": claim["claim_id"]}, {"$set": {"status": "PAYMENT_PENDING", "payment_expires_at": past}})
    expired = await muse_promo.expire_pending_claims(datetime.now(timezone.utc))
    assert len(expired) == 1
    assert expired[0]["claim_id"] == claim["claim_id"]
    doc = await db.muse_claims.find_one({"claim_id": claim["claim_id"]})
    assert doc["status"] == "PAYMENT_EXPIRED"
    assert doc.get("owner_message_id") is None

async def test_28_existing_gopay_deposit_remains_functional():
    user = {"telegram_id": 501, "username": "depuser", "first_name": "Dep"}
    from gopay_provider import create_gopay_payment
    import gopay_provider
    gopay_provider._run_node = lambda script, args=None, timeout=90: {"image_base64": "AAAA"}
    res = await create_gopay_payment(user, 50000, platform_code=105)
    assert res["deposit"]["amount"] == 50000
    assert res["deposit"]["platform_code"] == 105
    dep_in_db = await db.deposits.find_one({"_id": res["deposit"]["_id"]})
    assert dep_in_db is not None
