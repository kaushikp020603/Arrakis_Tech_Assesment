"""Guardrail for category 2 (unauthenticated access): HTTP Basic auth against scrypt-hashed passwords.

* passwords are stored only as salted scrypt hashes (data/users.json), never in clear text
* comparison is constant-time; unknown usernames are verified against a dummy hash so response time
  does not reveal which usernames exist
* wrong-password attempts are throttled per (ip, username) and per ip, which stops password guessing
"""
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .. import settings

_basic = HTTPBasic(auto_error=False)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, bytes.fromhex(digest))
    except Exception:
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))


class _FailureThrottle:
    def __init__(self, window: float = 60.0):
        self.window, self.lock = window, threading.Lock()
        self.events: dict = defaultdict(deque)

    def count(self, key) -> int:
        now = time.monotonic()
        with self.lock:
            q = self.events[key]
            while q and now - q[0] > self.window:
                q.popleft()
            return len(q)

    def add(self, key):
        with self.lock:
            self.events[key].append(time.monotonic())


_failures = _FailureThrottle()


def load_users() -> dict:
    try:
        return json.loads(settings.USERS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError("data/users.json is missing - run: python scripts/create_users.py")


_USERS: dict | None = None


def _users() -> dict:
    global _USERS
    if _USERS is None:
        _USERS = load_users()  # loaded on first request, so scripts can import hash_password before the file exists
    return _USERS


def current_user(request: Request, creds: HTTPBasicCredentials | None = Depends(_basic)) -> str:
    """FastAPI dependency: returns the authenticated username or raises 401 / 429."""
    challenge = {"WWW-Authenticate": 'Basic realm="llm-api"'}
    ip = request.client.host if request.client else "unknown"
    name = (creds.username if creds else "").strip().lower()

    if (_failures.count(("ip", ip)) >= settings.MAX_FAILS_PER_IP
            or _failures.count(("user", ip, name)) >= settings.MAX_FAILS_PER_USER_IP):
        raise HTTPException(429, detail={"detail": "Too many failed logins", "code": "E_LOCKED"},
                            headers={"Retry-After": "60"})
    if creds is None:
        raise HTTPException(401, detail={"detail": "Authentication required", "code": "E_AUTH"}, headers=challenge)

    stored = _users().get(name)
    ok = verify_password(creds.password, stored or _DUMMY_HASH) and stored is not None
    if not ok:
        _failures.add(("ip", ip))
        _failures.add(("user", ip, name))
        raise HTTPException(401, detail={"detail": "Invalid credentials", "code": "E_AUTH"}, headers=challenge)
    return name
