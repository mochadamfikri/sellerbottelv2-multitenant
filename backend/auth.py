import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel
from db import platform_db

JWT_ALGORITHM = "HS256"
router = APIRouter(prefix="/api/auth")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=12), "type": "access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


async def seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("ADMIN_EMAIL dan ADMIN_PASSWORD wajib di-set. Tidak ada default admin/password.")
    existing = await platform_db().admins.find_one({
        "$or": [
            {"_id": "admin-1"},
            {"email": email},
        ]
    })
    if existing is None:
        await platform_db().admins.insert_one({
            "_id": "admin-1", "email": email, "password_hash": hash_password(password),
            "name": "Admin", "role": "admin", "created_at": datetime.now(timezone.utc).isoformat(),
        })


async def get_current_admin(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await platform_db().admins.find_one({"_id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    email = body.email.lower().strip()
    trusted_proxy = os.environ.get("TRUST_PROXY", "").lower() in {"1", "true", "yes"}
    client_ip = request.client.host if request.client else "unknown"
    if trusted_proxy:
        client_ip = request.headers.get("x-forwarded-for", client_ip).split(",")[0].strip()
    identifier = f"{client_ip}:{email}"
    pdb = platform_db()
    attempt = await pdb.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("count", 0) >= 5:
        locked_at = datetime.fromisoformat(attempt["last_at"])
        if datetime.now(timezone.utc) - locked_at < timedelta(minutes=15):
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi dalam 15 menit.")
        await pdb.login_attempts.delete_one({"identifier": identifier})
    user = await pdb.admins.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        await pdb.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"last_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Email atau password salah")
    await pdb.login_attempts.delete_one({"identifier": identifier})
    token = create_access_token(user["_id"], email)
    secure_cookie = os.environ.get("COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
    response.set_cookie(key="access_token", value=token, httponly=True, secure=secure_cookie, samesite=os.environ.get("COOKIE_SAMESITE", "lax"), max_age=43200, path="/")
    return {"id": user["_id"], "email": email, "name": user.get("name", "Admin"), "token": token}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me")
async def me(admin: dict = Depends(get_current_admin)):
    return {"id": admin["_id"], "email": admin["email"], "name": admin.get("name", "Admin")}
