"""Password hashing and signed bearer tokens."""
import base64
import hashlib
import hmac
import json
import os
import time

from app import config


class AuthError(Exception):
    pass


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, config.PASSWORD_ITERATIONS
    )
    return "pbkdf2$%s$%s" % (_b64(salt), _b64(digest))


def check_password(password, stored):
    try:
        scheme, salt_text, digest_text = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    expected = hash_password(password, _unb64(salt_text))
    return hmac.compare_digest(expected, stored)


def _sign(message):
    key = config.TOKEN_SECRET.encode("utf-8")
    return hmac.new(key, message.encode("ascii"), hashlib.sha256).digest()


def issue_token(user_id, is_admin=False):
    payload = {
        "sub": user_id,
        "adm": bool(is_admin),
        "exp": int(time.time()) + config.TOKEN_TTL_MINUTES,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return "%s.%s" % (body, _b64(_sign(body)))


def read_token(token):
    try:
        body, signature = token.split(".")
    except ValueError:
        raise AuthError("malformed token")
    if not hmac.compare_digest(_b64(_sign(body)), signature):
        raise AuthError("bad signature")
    payload = json.loads(_unb64(body))
    if payload["exp"] < time.time():
        raise AuthError("token expired")
    return payload


def user_from_header(header_value):
    if not header_value or not header_value.startswith("Bearer "):
        raise AuthError("missing bearer token")
    return read_token(header_value[len("Bearer "):])


def ensure_admin(conn, db):
    """Create the first administrator from the environment when none exists."""
    if not config.ADMIN_PASSWORD:
        return None
    if db.get_user_by_email(conn, config.ADMIN_EMAIL):
        return None
    return db.create_user(
        conn,
        config.ADMIN_EMAIL,
        "Administrator",
        hash_password(config.ADMIN_PASSWORD),
        is_admin=True,
    )
