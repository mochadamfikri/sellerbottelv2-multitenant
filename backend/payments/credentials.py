import json
from uuid import uuid4
from inventory import _fernet
from commerce.fulfillment_types import CommerceError
from .models import now
from .providers.registry import provider, SCHEMAS

def seal(binding, fields):
    return _fernet().encrypt(json.dumps({"binding": binding, "fields": fields}, separators=(",", ":")).encode()).decode()

def unseal(binding, ciphertext):
    try:
        value = json.loads(_fernet().decrypt(ciphertext.encode()))
        if value["binding"] != binding:
            raise ValueError
        return value["fields"]
    except Exception:
        raise CommerceError("Credential binding or decryption failed") from None

def binding(database, tenant_id, name, environment, version):
    return f"gateway:{database.name}:{tenant_id}:{name}:{environment}:{version}"

async def save(database, tenant_id, name, environment, fields):
    if name not in SCHEMAS or environment not in {"mock", "sandbox"} or not isinstance(fields, dict) or set(fields) - set(SCHEMAS[name]):
        raise CommerceError("Invalid credential schema")
    required = {"api_key", "webhook_secret"} if name == "kasera" else {"server_key", "client_key"}
    if not required.issubset(fields) or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in fields.values()):
        raise CommerceError("Missing provider credentials")
    if environment == "sandbox" and name == "kasera" and not fields["api_key"].startswith("kp_test_"):
        raise CommerceError("Kasera sandbox requires kp_test_ key")
    version = str(uuid4())
    doc = {"_id": version, "tenant_id": tenant_id, "provider": name, "environment": environment, "created_at": now(), "revoked": False,
           "secret": seal(binding(database, tenant_id, name, environment, version), fields), "masked_fields": {k: "••••" for k in fields}}
    await database.gateway_credentials.insert_one(doc)
    await database.payment_settings.update_one({"_id": "main"}, {"$set": {"provider": name, "environment": environment, "credential_id": version, "capabilities": None}}, upsert=True)
    return version

async def load(database, tenant_id, credential_id, *, historical=False):
    doc = await database.gateway_credentials.find_one({"_id": credential_id, "tenant_id": tenant_id})
    if not doc or (doc.get("revoked") and not historical):
        raise CommerceError("Gateway credentials unavailable")
    fields = unseal(binding(database, tenant_id, doc["provider"], doc["environment"], credential_id), doc["secret"])
    return provider(doc["provider"], doc["environment"], fields)

async def test_connection(database, tenant_id):
    config = await database.payment_settings.find_one({"_id": "main"}) or {}
    adapter = await load(database, tenant_id, config.get("credential_id"))
    caps = await adapter.connect()
    await database.payment_settings.update_one({"_id": "main", "credential_id": config["credential_id"]}, {"$set": {"capabilities": caps}})
    return caps
