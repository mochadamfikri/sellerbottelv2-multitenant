import os
import json
import httpx

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")


def _current_token() -> str:
    """Bot token for the ambient tenant scope, else the legacy env token."""
    try:
        from bot_tenant_scope import get_current_scope
        scope = get_current_scope()
        if scope is not None and scope.bot_token:
            return scope.bot_token
    except Exception:
        pass
    return TOKEN


def _api() -> str:
    return f"https://api.telegram.org/bot{_current_token()}"


def _file_api() -> str:
    return f"https://api.telegram.org/file/bot{_current_token()}"


# Kept for backwards compatibility; prefer _api()/_file_api() for sends.
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"


_shared_client: httpx.AsyncClient | None = None


def _client(timeout: int = 30) -> httpx.AsyncClient:
    """Sandbox-hardened HTTP client for Telegram API calls.

    trust_env=False: the sandbox NO_PROXY carries bracketed IPv6 entries
    that this httpx version cannot parse.  Proxy and CA bundle are set
    explicitly instead (the proxy MITMs TLS with a custom CA).
    """
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    verify = os.environ.get("SSL_CERT_FILE") or True
    return httpx.AsyncClient(timeout=timeout, proxy=proxy,
                             trust_env=False, verify=verify)


def get_shared_client() -> httpx.AsyncClient:
    """Process-wide persistent client with connection pooling.

    Creating a fresh client per API call costs ~1s of proxy CONNECT +
    TLS handshake every time; reuse keeps subsequent calls at ~0.25s.
    Safe for concurrent use from tasks on the same event loop.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        verify = os.environ.get("SSL_CERT_FILE") or True
        _shared_client = httpx.AsyncClient(
            timeout=30, proxy=proxy, trust_env=False, verify=verify,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=30,
                                keepalive_expiry=60),
        )
    return _shared_client


async def tg(method: str, **payload):
    c = get_shared_client()
    r = await c.post(f"{_api()}/{method}", json=payload)
    return r.json()


async def send_message(chat_id, text, kb=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        payload["reply_markup"] = kb
    return await tg("sendMessage", **payload)


async def edit_message(chat_id, message_id, text, kb=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        payload["reply_markup"] = kb
    return await tg("editMessageText", **payload)


async def delete_message(chat_id, message_id):
    return await tg("deleteMessage", chat_id=chat_id, message_id=message_id)


async def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    return await tg("answerCallbackQuery", **payload)


async def send_photo_by_id(chat_id, file_id, caption=None, kb=None):
    payload = {"chat_id": chat_id, "photo": file_id, "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    if kb:
        payload["reply_markup"] = kb
    return await tg("sendPhoto", **payload)


async def send_photo_by_url(chat_id, url, caption=None, kb=None):
    """Send a photo from an http(s) URL (Telegram fetches it server-side)."""
    return await send_photo_by_id(chat_id, url, caption=caption, kb=kb)


async def send_animation_by_id(chat_id, file_id, caption=None, kb=None):
    """Send a GIF animation via Telegram file_id."""
    payload = {"chat_id": chat_id, "animation": file_id, "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    if kb:
        payload["reply_markup"] = kb
    return await tg("sendAnimation", **payload)


async def send_animation_by_url(chat_id, url, caption=None, kb=None):
    """Send a GIF animation from an http(s) URL."""
    return await send_animation_by_id(chat_id, url, caption=caption, kb=kb)


async def send_animation_bytes(chat_id, data: bytes, filename: str = "anim.gif",
                              caption=None, kb=None):
    """Upload and send a GIF animation from raw bytes."""
    payload = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    if kb:
        payload["reply_markup"] = json.dumps(kb, ensure_ascii=False, separators=(",", ":"))
    r = await get_shared_client().post(
        f"{_api()}/sendAnimation",
        data=payload,
        files={"animation": (filename, data, "image/gif")},
        timeout=120,
    )
    return r.json()


async def send_video_by_id(chat_id, file_id, caption=None, kb=None):
    """Send a video via Telegram file_id."""
    payload = {"chat_id": chat_id, "video": file_id, "parse_mode": "HTML",
               "supports_streaming": True}
    if caption:
        payload["caption"] = caption
    if kb:
        payload["reply_markup"] = kb
    return await tg("sendVideo", **payload)


async def send_video_by_url(chat_id, url, caption=None, kb=None):
    """Send a video from an http(s) URL (Telegram fetches it server-side)."""
    return await send_video_by_id(chat_id, url, caption=caption, kb=kb)


async def send_video_bytes(chat_id, data: bytes, filename: str = "video.mp4",
                           caption=None, kb=None):
    """Upload and send a video from raw bytes."""
    payload = {"chat_id": str(chat_id), "parse_mode": "HTML",
               "supports_streaming": "true"}
    if caption:
        payload["caption"] = caption
    if kb:
        payload["reply_markup"] = json.dumps(kb, ensure_ascii=False, separators=(",", ":"))
    r = await get_shared_client().post(
        f"{_api()}/sendVideo",
        data=payload,
        files={"video": (filename, data, "video/mp4")},
        timeout=180,
    )
    return r.json()


async def send_photo_bytes(chat_id, data: bytes, filename: str = "photo.jpg", caption=None, kb=None):
    payload = {"chat_id": str(chat_id)}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    if kb:
        payload["reply_markup"] = json.dumps(kb, ensure_ascii=False, separators=(",", ":"))
    r = await get_shared_client().post(
        f"{_api()}/sendPhoto",
        data=payload,
        files={"photo": (filename, data, "image/jpeg")},
        timeout=120,
    )
    return r.json()


async def send_document(chat_id, data: bytes, filename: str, caption=None):
    payload = {"chat_id": str(chat_id)}
    if caption:
        payload["caption"] = caption
    r = await get_shared_client().post(
        f"{_api()}/sendDocument", data=payload, files={"document": (filename, data)},
        timeout=120,
    )
    return r.json()


async def download_telegram_file(file_id: str):
    c = get_shared_client()
    r = await c.post(f"{_api()}/getFile", json={"file_id": file_id}, timeout=60)
    info = r.json()
    if not info.get("ok"):
        return None
    path = info["result"]["file_path"]
    f = await c.get(f"{_file_api()}/{path}", timeout=60)
    return f.content
