"""Read-only release evidence. Output contains IDs and hashes, never credentials."""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from bson import json_util
from db import db


async def main():
    destination = Path(sys.argv[1])
    result = {}
    for collection in ("products", "inventory_items", "purchases", "bot_users", "deposits", "store_customers", "gopay_payments"):
        rows = await db[collection].find({}).to_list(None)
        result[collection] = {str(row["_id"]): hashlib.sha256(json_util.dumps(row, sort_keys=True).encode()).hexdigest() for row in rows}
    result["summary"] = {name: len(rows) for name, rows in result.items()}
    result["summary"]["active_products"] = await db.products.count_documents({"active": True})
    result["summary"]["sold_inventory"] = await db.inventory_items.count_documents({"status": "sold"})
    settings = await db.settings.find_one({"_id": "main"}) or {}
    result["summary"]["followup_mode"] = (settings.get("post_purchase_followup") or {}).get("mode", "none")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(result, stream)
    print(json.dumps(result["summary"]))
    if len(sys.argv) > 2:
        previous = json.loads(Path(sys.argv[2]).read_text())
        changes = {}
        for name, rows in result.items():
            if name == "summary":
                continue
            before = previous[name]
            changes[name] = {"missing": len(set(before) - set(rows)), "new": len(set(rows) - set(before)), "changed": sum(rows[key] != before[key] for key in rows.keys() & before.keys())}
        print(json.dumps(changes))
        assert all(row["missing"] == 0 for row in changes.values()), "Existing records disappeared; review before continuing."


asyncio.run(main())
