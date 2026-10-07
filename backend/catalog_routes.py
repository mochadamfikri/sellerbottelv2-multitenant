"""Admin catalog management; inventory remains attached to product IDs."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from db import db
from product_catalog import catalog_name

router = APIRouter(prefix="/catalogs")


class CatalogBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Nama katalog wajib diisi.")
        return value


class AssignBody(CatalogBody):
    product_ids: list[str] = Field(min_length=1, max_length=5000)


class RenameBody(CatalogBody):
    old_name: str = Field(min_length=1, max_length=80)


async def catalog_products():
    return await db.products.find({}, {
        "name": 1, "catalog_name": 1, "product_kind": 1, "active": 1,
    }).to_list(length=None)


@router.get("")
async def list_catalogs():
    groups = {row["_id"]: {"name": row["name"], "products": []} for row in
              await db.product_catalogs.find({}).to_list(length=None)}
    for product in await catalog_products():
        name = catalog_name(product)
        key = name.lower()
        groups.setdefault(key, {"name": name, "products": []})["products"].append({
            "_id": str(product["_id"]), "name": product.get("name", ""),
            "active": product.get("active", True),
        })
    return sorted(groups.values(), key=lambda row: row["name"].lower())


@router.post("")
async def create_catalog(body: CatalogBody):
    await db.product_catalogs.update_one({"_id": body.name.lower()},
        {"$setOnInsert": {"name": body.name}}, upsert=True)
    return {"ok": True}


@router.put("/assign")
async def assign_catalog(body: AssignBody):
    ids = list(set(body.product_ids))
    if await db.products.count_documents({"_id": {"$in": ids}}) != len(ids):
        raise HTTPException(404, "Salah satu produk tidak ditemukan. Muat ulang daftar produk.")
    await create_catalog(body)
    record = await db.product_catalogs.find_one({"_id": body.name.lower()})
    result = await db.products.update_many({"_id": {"$in": ids}}, {"$set": {"catalog_name": record["name"]}})
    return {"ok": True, "matched": result.matched_count}


@router.put("/rename")
async def rename_catalog(body: RenameBody):
    old_key = " ".join(body.old_name.split()).lower()
    groups = await list_catalogs()
    old = next((row for row in groups if row["name"].lower() == old_key), None)
    if not old:
        raise HTTPException(404, "Katalog tidak ditemukan.")
    if old_key == "produk lainnya":
        raise HTTPException(400, "Pindahkan produk dari katalog umum ke katalog pilihan.")
    if old_key != body.name.lower() and any(row["name"].lower() == body.name.lower() for row in groups):
        raise HTTPException(409, "Nama katalog sudah ada. Gunakan pindahkan produk untuk menggabungkan katalog.")
    await db.product_catalogs.update_one({"_id": body.name.lower()}, {"$set": {"name": body.name}}, upsert=True)
    await db.products.update_many({"_id": {"$in": [p["_id"] for p in old["products"]]}},
                                 {"$set": {"catalog_name": body.name}})
    settings = await db.settings.find_one({"_id": "main"}) or {}
    excluded = (settings.get("post_purchase_followup") or {}).get("exempt_catalogs", [])
    if any(value.strip().lower() == old_key for value in excluded):
        await db.settings.update_one({"_id": "main"}, {"$set": {
            "post_purchase_followup.exempt_catalogs": [body.name if value.strip().lower() == old_key else value for value in excluded],
        }})
    if old_key != body.name.lower():
        await db.product_catalogs.delete_one({"_id": old_key})
    return {"ok": True}


@router.delete("")
async def delete_catalog(name: str):
    key = " ".join(name.split()).lower()
    if key == "produk lainnya":
        raise HTTPException(400, "Katalog umum tidak dapat dihapus.")
    group = next((row for row in await list_catalogs() if row["name"].lower() == key), None)
    if not group:
        raise HTTPException(404, "Katalog tidak ditemukan.")
    await db.products.update_many({"_id": {"$in": [p["_id"] for p in group["products"]]}},
                                 {"$set": {"catalog_name": "Produk Lainnya"}})
    settings = await db.settings.find_one({"_id": "main"}) or {}
    excluded = (settings.get("post_purchase_followup") or {}).get("exempt_catalogs", [])
    if any(value.strip().lower() == key for value in excluded):
        # Preserve the exception for these products without exempting unrelated products.
        await db.settings.update_one({"_id": "main"}, {
            "$set": {"post_purchase_followup.exempt_catalogs": [value for value in excluded if value.strip().lower() != key]},
            "$addToSet": {"post_purchase_followup.exempt_product_ids": {"$each": [p["_id"] for p in group["products"]]}},
        })
    await db.product_catalogs.delete_one({"_id": key})
    return {"ok": True}
