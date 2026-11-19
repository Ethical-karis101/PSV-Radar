"""Human authentication using salted scrypt passwords and opaque sessions."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.database import DATABASE_PATH

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "psv_session"
SESSION_DAYS = 30


def _now():
    return datetime.now(timezone.utc)


def _db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${derived.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored.split("$", 2)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(derived.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _user_response(row):
    return {"user_id": row["user_id"], "name": row["name"], "email": row["email"],
            "role": row["role"], "organization_id": row["organization_id"]}


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ConductorAccountRequest(BaseModel):
    conductor_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)


def _set_session(response: Response, user_id: str):
    raw_token = secrets.token_urlsafe(48)
    expires = _now() + timedelta(days=SESSION_DAYS)
    with _db() as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), user_id, hashlib.sha256(raw_token.encode()).hexdigest(),
             expires.isoformat(), _now().isoformat()),
        )
    response.set_cookie(SESSION_COOKIE, raw_token, max_age=SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=os.getenv("PSV_RADAR_SECURE_COOKIES", "0") == "1",
                        path="/")


def current_user(psv_session: str | None = Cookie(default=None)):
    if not psv_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    token_hash = hashlib.sha256(psv_session.encode()).hexdigest()
    with closing(_db()) as connection:
        row = connection.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.user_id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
            (token_hash, _now().isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return row


def require_owner(user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required.")
    return user


@router.post("/register", status_code=201)
def register(request: RegisterRequest, response: Response):
    email = request.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Enter a valid email address.")
    organization_id = str(uuid4())
    user_id = str(uuid4())
    with _db() as connection:
        try:
            connection.execute("INSERT INTO organizations VALUES (?, ?, ?)",
                               (organization_id, f"{request.name.strip()}'s operations", _now().isoformat()))
            connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, 'owner', 1, ?)",
                               (user_id, organization_id, request.name.strip(), email,
                                _password_hash(request.password), _now().isoformat()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "An account with this email already exists.") from error
        user = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    _set_session(response, user_id)
    return {"user": _user_response(user)}


@router.post("/login")
def login(request: LoginRequest, response: Response):
    email = request.email.strip().lower()
    with closing(_db()) as connection:
        user = connection.execute("SELECT * FROM users WHERE email = ? AND active = 1", (email,)).fetchone()
    if user is None or not _password_matches(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    _set_session(response, user["user_id"])
    return {"user": _user_response(user)}


@router.post("/conductors", status_code=201)
def create_conductor_account(request: ConductorAccountRequest, owner=Depends(require_owner)):
    email = request.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Enter a valid email address.")
    user_id = str(uuid4())
    with _db() as connection:
        try:
            connection.execute(
                "INSERT INTO conductors (conductor_id, name, phone, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (request.conductor_id, request.name.strip(), request.phone, _now().isoformat()),
            )
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, 'conductor', 1, ?)",
                (user_id, owner["organization_id"], request.name.strip(), email,
                 _password_hash(request.password), _now().isoformat()),
            )
            connection.execute("UPDATE conductors SET user_id = ? WHERE conductor_id = ?",
                               (user_id, request.conductor_id))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Conductor ID or email already exists.") from error
    return {"user": {"user_id": user_id, "name": request.name.strip(), "email": email,
                      "role": "conductor", "organization_id": owner["organization_id"]}}


@router.get("/conductors")
def list_conductor_accounts(owner=Depends(require_owner)):
    with closing(_db()) as connection:
        rows = connection.execute(
            """SELECT u.user_id, u.name, u.email, u.active, c.conductor_id, c.phone
               FROM users u JOIN conductors c ON c.user_id = u.user_id
               WHERE u.organization_id = ? AND u.role = 'conductor'
               ORDER BY u.name""",
            (owner["organization_id"],),
        ).fetchall()
    return {"conductors": [dict(row) for row in rows]}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": _user_response(user)}


@router.post("/logout")
def logout(response: Response, psv_session: str | None = Cookie(default=None)):
    if psv_session:
        with _db() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?",
                               (hashlib.sha256(psv_session.encode()).hexdigest(),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "signed_out"}
