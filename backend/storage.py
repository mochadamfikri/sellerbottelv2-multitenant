"""Local filesystem-backed object storage for product files.

Files live on the VPS instead of relying on an external object-storage service.
The database stores only the relative storage path.
"""

import asyncio
import mimetypes
import os
import uuid
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
STORAGE_ROOT = Path(
    os.environ.get("LOCAL_STORAGE_DIR") or (ROOT_DIR / "storage_data")
).expanduser().resolve()


def _resolve_path(relative_path: str) -> Path:
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValueError("Invalid storage path")

    target = (STORAGE_ROOT / raw).resolve()
    try:
        target.relative_to(STORAGE_ROOT)
    except ValueError as exc:
        raise ValueError("Invalid storage path") from exc
    return target


async def init_storage() -> str:
    await asyncio.to_thread(STORAGE_ROOT.mkdir, parents=True, exist_ok=True)
    return str(STORAGE_ROOT)


async def put_object(path: str, data: bytes, content_type: str) -> dict:
    await init_storage()
    target = _resolve_path(path)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)

    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        await asyncio.to_thread(temp.write_bytes, data)
        await asyncio.to_thread(temp.replace, target)
    finally:
        if temp.exists():
            try:
                await asyncio.to_thread(temp.unlink)
            except FileNotFoundError:
                pass

    return {
        "path": target.relative_to(STORAGE_ROOT).as_posix(),
        "content_type": content_type or "application/octet-stream",
        "size": len(data),
    }


async def get_object(path: str):
    await init_storage()
    target = _resolve_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Stored object not found: {path}")

    data = await asyncio.to_thread(target.read_bytes)
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return data, content_type


async def delete_object(path: str) -> bool:
    target = _resolve_path(path)
    if not target.is_file():
        return False
    await asyncio.to_thread(target.unlink)
    return True
