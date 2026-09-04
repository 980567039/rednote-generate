"""轻量账号与会话服务。

使用 SQLite 持久化账号和会话，只保存密码派生结果与会话令牌哈希。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
SESSION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCRYPT_N = 32_768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 64
SCRYPT_MAX_MEMORY = 64 * 1024 * 1024
_DUMMY_PASSWORD_HASH: Optional[str] = None


class AuthError(RuntimeError):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    display_name: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "displayName": self.display_name,
            "role": "user",
        }


@dataclass(frozen=True)
class AuthResult:
    user: AuthUser
    session_token: str


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()


def validate_registration_input(data: object) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        raise AuthError("INVALID_JSON", "请求体必须是 JSON 对象。", 400)
    email = normalize_email(str(data.get("email") or ""))
    display_name = unicodedata.normalize(
        "NFKC", str(data.get("displayName") or "")
    ).strip()
    password = data.get("password")
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 320:
        raise AuthError("VALIDATION_ERROR", "邮箱格式不正确。", 400)
    if not display_name or len(display_name) > 40:
        raise AuthError("VALIDATION_ERROR", "昵称必须为 1–40 个字符。", 400)
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise AuthError("VALIDATION_ERROR", "密码必须为 8–128 个字符。", 400)
    return email, display_name, password


def validate_login_input(data: object) -> tuple[str, str]:
    if not isinstance(data, dict):
        raise AuthError("INVALID_JSON", "请求体必须是 JSON 对象。", 400)
    email = normalize_email(str(data.get("email") or ""))
    password = data.get("password")
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 320:
        raise AuthError("VALIDATION_ERROR", "邮箱格式不正确。", 400)
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        raise AuthError("VALIDATION_ERROR", "密码不能为空。", 400)
    return email, password


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAX_MEMORY,
        dklen=SCRYPT_KEY_LENGTH,
    )


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    key = _derive_password(password, actual_salt)
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{_encode_base64(actual_salt)}${_encode_base64(key)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_text, key_text = encoded.split("$")
        if (
            algorithm != "scrypt"
            or int(n_text) != SCRYPT_N
            or int(r_text) != SCRYPT_R
            or int(p_text) != SCRYPT_P
        ):
            return False
        salt = _decode_base64(salt_text)
        expected = _decode_base64(key_text)
        if len(salt) != 16 or len(expected) != SCRYPT_KEY_LENGTH:
            return False
        return hmac.compare_digest(_derive_password(password, salt), expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def _dummy_password_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password(
            "redink-invalid-password", b"redink-auth-salt"
        )
    return _DUMMY_PASSWORD_HASH


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class AuthService:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    normalized_email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS sessions_user_expiry_idx
                    ON sessions(user_id, expires_at);
                """
            )
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def registration_status(self) -> dict:
        with self._connect() as connection:
            user_count = connection.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
        return {"registrationOpen": user_count == 0}

    def register(self, data: object) -> AuthResult:
        email, display_name, password = validate_registration_input(data)
        password_hash = hash_password(password)
        user_id = str(uuid.uuid4())
        created_at = _timestamp(_utc_now())
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                    raise AuthError(
                        "REGISTRATION_CLOSED", "站点账号已创建，请直接登录。", 409
                    )
                connection.execute(
                    """
                    INSERT INTO users (
                        id, email, normalized_email, display_name,
                        password_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        email,
                        display_name,
                        password_hash,
                        created_at,
                    ),
                )
        except AuthError:
            raise
        except sqlite3.IntegrityError as exc:
            raise AuthError(
                "EMAIL_ALREADY_REGISTERED", "该邮箱已注册。", 409
            ) from exc
        user = AuthUser(user_id, email, display_name)
        return AuthResult(user, self._create_session(user_id))

    def login(self, data: object) -> AuthResult:
        email, password = validate_login_input(data)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name, password_hash
                FROM users WHERE normalized_email = ?
                """,
                (email,),
            ).fetchone()
        password_hash = row["password_hash"] if row else _dummy_password_hash()
        password_matches = verify_password(password, password_hash)
        if not row or not password_matches:
            raise AuthError("UNAUTHORIZED", "邮箱或密码不正确。", 401)
        user = AuthUser(row["id"], row["email"], row["display_name"])
        return AuthResult(user, self._create_session(user.id))

    def _create_session(self, user_id: str) -> str:
        now = _utc_now()
        expires_at = now + timedelta(seconds=SESSION_TTL_SECONDS)
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO sessions (
                            id, user_id, token_hash, expires_at,
                            revoked_at, created_at
                        ) VALUES (?, ?, ?, ?, NULL, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            user_id,
                            _token_hash(token),
                            _timestamp(expires_at),
                            _timestamp(now),
                        ),
                    )
                return token
            except sqlite3.IntegrityError:
                continue
        raise AuthError("LOGIN_FAILED", "登录失败，请稍后重试。", 503)

    def authenticated_user(self, token: Optional[str]) -> Optional[AuthUser]:
        if not token or not SESSION_TOKEN_PATTERN.fullmatch(token):
            return None
        token_hash = _token_hash(token)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.expires_at, s.revoked_at,
                       u.id, u.email, u.display_name
                FROM sessions AS s
                JOIN users AS u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row or row["revoked_at"]:
                return None
            if _parse_timestamp(row["expires_at"]) <= _utc_now():
                connection.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
                    (_timestamp(_utc_now()), token_hash),
                )
                return None
        return AuthUser(row["id"], row["email"], row["display_name"])

    def revoke_session(self, token: Optional[str]) -> bool:
        if not token or not SESSION_TOKEN_PATTERN.fullmatch(token):
            return False
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE sessions SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (_timestamp(_utc_now()), _token_hash(token)),
            )
        return result.rowcount > 0
