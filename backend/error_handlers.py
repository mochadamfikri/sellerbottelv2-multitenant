"""Handler error terpusat.

Tujuan utama: admin panel selalu menerima JSON ``{"detail": ...}`` yang jelas,
bukan ``Internal Server Error`` polos yang di frontend berubah menjadi
"Terjadi kesalahan. Coba lagi." tanpa petunjuk penyebabnya.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from inventory import InventoryError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Daftarkan handler error.

    Panggil SEBELUM ``CORSMiddleware`` ditambahkan supaya respons error 500 tetap
    melewati CORS (jika tidak, browser menampilkannya sebagai "Network Error").
    """

    @app.exception_handler(InventoryError)
    async def inventory_error_handler(request: Request, exc: InventoryError):
        if exc.status_code >= 500:
            logger.error("Inventory error on %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.middleware("http")
    async def unhandled_error_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - penjaga terakhir
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": f"Kesalahan server ({type(exc).__name__}). Cek log backend."},
            )
