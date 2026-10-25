"""Optional shared recruiter passcode.

Recruiter routes are open unless ``RECRUITER_AUTH_REQUIRED`` is true.
``RECRUITER_PASSCODE`` by itself does not lock the app. When the flag is on,
the browser keeps a signed token and each request recomputes the HMAC.
"""

import base64
import hashlib
import hmac
import os
import time

from fastapi import Header, HTTPException

TOKEN_TTL_SECONDS = 12 * 60 * 60
UNCONFIGURED_DETAIL = (
    "Recruiter access is not configured. Set RECRUITER_PASSCODE on the server."
)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def recruiter_auth_required() -> bool:
    return _flag("RECRUITER_AUTH_REQUIRED")


def recruiter_passcode() -> str:
    return os.getenv("RECRUITER_PASSCODE", "").strip()


def issue_token(passcode: str, now: int | None = None) -> str:
    exp = int(now if now is not None else time.time()) + TOKEN_TTL_SECONDS
    signature = hmac.new(passcode.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    raw = f"{exp}.{signature}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def token_is_valid(token: str, passcode: str, now: int | None = None) -> bool:
    if not token or not passcode:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        exp_text, signature = raw.split(".", 1)
        exp = int(exp_text)
    except Exception:
        return False
    current = int(now if now is not None else time.time())
    if exp < current:
        return False
    expected = hmac.new(passcode.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def require_recruiter(authorization: str | None = Header(default=None)) -> None:
    if not recruiter_auth_required():
        return
    passcode = recruiter_passcode()
    if not passcode:
        raise HTTPException(status_code=503, detail=UNCONFIGURED_DETAIL)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Recruiter sign-in required.")
    token = authorization.split(" ", 1)[1].strip()
    if not token_is_valid(token, passcode):
        raise HTTPException(status_code=401, detail="Recruiter sign-in required.")
