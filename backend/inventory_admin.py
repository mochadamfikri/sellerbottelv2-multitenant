"""Templates and safe edits for individual available inventory records."""
import io
import csv
import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from db import db
from inventory import normalize_record, _fernet, _canonical, now_iso, available_count

router = APIRouter(prefix="/products/{pid}/inventory")


def validate_schema(fields):
    schema = [str(field).strip() for field in fields]
    if not schema or len(schema) > 50 or any(not field or len(field) > 80 or field.startswith("__") for field in schema):
        raise HTTPException(400, "Isi 1–50 nama kolom, maksimal 80 karakter per kolom; awalan __ tidak diperbolehkan.")
    if len({field.casefold() for field in schema}) != len(schema):
        raise HTTPException(400, "Nama kolom tidak boleh duplikat.")
    return schema


def align_records(schema, records, expected):
    schema = validate_schema(schema)
    if not expected:
        return schema, records
    mapping = {key.strip().casefold(): key for key in schema}
    if set(mapping) != {key.strip().casefold() for key in expected}:
        raise HTTPException(400, f"Header inventory tidak cocok. Kolom wajib: {' | '.join(expected)}. Kolom diterima: {' | '.join(schema)}.")
    return expected, [{**{key: row.get(mapping[key.strip().casefold()], "") for key in expected},
                        **{key: value for key, value in row.items() if key in {"__file_name", "__file_data_b64"}}} for row in records]


def parse_text_records(text, schema):
    rows = [row for row in csv.reader(io.StringIO(text), delimiter="|") if any(cell.strip() for cell in row)]
    if not rows:
        raise HTTPException(400, "Data inventory kosong.")
    first = [value.strip() for value in rows[0]]
    if not schema:
        schema = validate_schema(first)
        rows = rows[1:]
    elif {value.casefold() for value in first} == {value.casefold() for value in schema}:
        incoming = first
        records = []
        for row in rows[1:]:
            if len(row) != len(incoming):
                raise HTTPException(400, "Jumlah kolom TXT tidak sesuai header.")
            records.append(dict(zip(incoming, row)))
        return align_records(incoming, records, schema)
    records = []
    for row in rows:
        if len(row) != len(schema):
            raise HTTPException(400, f"Gunakan {len(schema)} kolom dipisahkan | sesuai template inventory.")
        records.append(dict(zip(schema, row)))
    return schema, records


async def get_product(pid):
    product = await db.products.find_one({"_id": pid})
    if not product:
        raise HTTPException(404, "Produk tidak ditemukan.")
    if product.get("product_kind") == "service":
        raise HTTPException(400, "Produk jasa tidak memakai inventory.")
    return product


class SchemaBody(BaseModel):
    fields: list[str] = Field(min_length=1, max_length=50)


@router.put("/schema")
async def set_schema(pid: str, body: SchemaBody):
    product = await get_product(pid)
    if product.get("inventory_mode") == "telegram_session":
        raise HTTPException(400, "Mode session menggunakan file .session.")
    schema = validate_schema(body.fields)
    if product.get("inventory_schema"):
        raise HTTPException(409, "Schema sudah ditetapkan. Gunakan kolom yang ada agar data lama tetap sesuai.")
    if await db.inventory_items.count_documents({"product_id": pid}):
        raise HTTPException(409, "Produk sudah mempunyai inventory.")
    result = await db.products.update_one({"_id": pid, "inventory_schema": product.get("inventory_schema")},
        {"$set": {"inventory_schema": schema, "updated_at": now_iso()}})
    if not result.matched_count:
        raise HTTPException(409, "Schema berubah. Muat ulang halaman.")
    return {"schema": schema}


@router.get("/template")
async def inventory_template(pid: str, format: str = "xlsx"):
    product = await get_product(pid)
    if product.get("inventory_mode") == "telegram_session":
        raise HTTPException(400, "Upload file .session asli; mode ini tidak memakai template tabel.")
    schema = product.get("inventory_schema") or ["email", "password"]
    if format == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "inventory"; ws.append(schema)
        ws.freeze_panes = "A2"
        info = wb.create_sheet("Petunjuk")
        info.append(["Produk", product.get("name", "")]); info.append(["Katalog", product.get("catalog_name", "Otomatis")])
        info.append(["Format", "Sheet inventory: header kolom, lalu satu item per baris. Jangan menambahkan kolom katalog ke data inventory."])
        out = io.BytesIO(); wb.save(out); content = out.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif format in {"txt", "csv"}:
        out = io.StringIO(); writer = csv.writer(out, delimiter="|" if format == "txt" else ",")
        writer.writerow(schema); content = out.getvalue().encode("utf-8-sig"); mime = "text/plain" if format == "txt" else "text/csv"
    else:
        raise HTTPException(400, "Pilih format xlsx, csv, atau txt.")
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="inventory-template.{format}"'})


class EditBody(BaseModel):
    data: dict[str, str]


async def save_record(pid, item_id, record, schema):
    clean, fingerprint, _ = normalize_record(record, schema)
    if not clean:
        raise HTTPException(400, "Data inventory tidak boleh kosong.")
    if await db.inventory_items.find_one({"product_id": pid, "fingerprint": fingerprint, "_id": {"$ne": item_id}}):
        raise HTTPException(409, "Data inventory tersebut sudah ada.")
    try:
        result = await db.inventory_items.update_one({"_id": item_id, "product_id": pid, "status": "available"},
            {"$set": {"secret": _fernet().encrypt(_canonical(clean).encode()).decode(), "fingerprint": fingerprint, "updated_at": now_iso()}})
    except DuplicateKeyError:
        raise HTTPException(409, "Data inventory tersebut sudah ada.")
    if not result.matched_count:
        raise HTTPException(409, "Item sudah dipesan/terjual atau tidak ditemukan. Muat ulang inventory.")
    return {"ok": True, "stock": await available_count(pid)}


@router.put("/{item_id}")
async def edit_inventory(pid: str, item_id: str, body: EditBody):
    product = await get_product(pid)
    if product.get("inventory_mode") == "telegram_session" or product.get("inventory_schema") == ["Session File"]:
        raise HTTPException(400, "Gunakan ganti file untuk inventory session.")
    schema, records = align_records(list(body.data), [body.data], product.get("inventory_schema") or [])
    return await save_record(pid, item_id, records[0], schema)


@router.post("/{item_id}/file")
async def replace_inventory_file(pid: str, item_id: str, file: UploadFile = File(...)):
    from admin_routes import _parse_inventory_input
    product = await get_product(pid)
    if product.get("inventory_mode") != "telegram_session" and product.get("inventory_schema") != ["Session File"]:
        raise HTTPException(400, "Ganti file hanya untuk inventory session.")
    schema, records = await _parse_inventory_input(file, "", product)
    if len(records) != 1:
        raise HTTPException(400, "Pilih satu file pengganti.")
    return await save_record(pid, item_id, records[0], schema)
