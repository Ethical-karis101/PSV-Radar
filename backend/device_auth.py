"""Short-lived authentication for camera edge agents."""

import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from backend.database import DATABASE_PATH

router = APIRouter(prefix="/device", tags=["device-auth"])


def now():
    return datetime.now(timezone.utc)


def db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_device_token(connection, device_id: str):
    token = secrets.token_urlsafe(48)
    connection.execute(
        "UPDATE camera_devices SET token_hash = ? WHERE device_id = ?",
        (token_hash(token), device_id),
    )
    return token


def issue_camera_session(connection, device_id: str, trip_id: str):
    token = secrets.token_urlsafe(48)
    expires = now() + timedelta(hours=12)
    connection.execute(
        "INSERT INTO camera_sessions VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (secrets.token_urlsafe(18), device_id, trip_id, token_hash(token),
         expires.isoformat(), now().isoformat()),
    )
    return token, expires


class DeviceSessionRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    device_token: str = Field(min_length=20, max_length=200)
    trip_id: str = Field(min_length=1, max_length=80)


class DeviceStatusRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    device_token: str = Field(min_length=20, max_length=200)


def _authenticated_device(connection, device_id, device_token):
    device = connection.execute(
        "SELECT * FROM camera_devices WHERE device_id = ? AND active = 1",
        (device_id,),
    ).fetchone()
    if device is None or not secrets.compare_digest(
        device["token_hash"], token_hash(device_token)
    ):
        raise HTTPException(status_code=401, detail="Device credential is invalid.")
    return device


@router.post("/active-trip")
def get_device_active_trip(request: DeviceStatusRequest):
    """Return only the active trip attached to the authenticated device's vehicle."""
    with closing(db()) as connection:
        device = _authenticated_device(connection, request.device_id, request.device_token)
        trips = connection.execute(
            """SELECT t.trip_id, t.route_id, t.direction, t.started_at,
                      t.current_stage_id,
                      cs.name AS current_stage_name,
                      r.name AS route_name, r.origin, r.destination
               FROM trips t JOIN routes r ON r.route_id = t.route_id
               LEFT JOIN route_stages cs ON cs.route_id = t.route_id AND cs.stage_id = t.current_stage_id
               WHERE t.vehicle_id = ? AND t.status = 'active'
               ORDER BY t.started_at DESC LIMIT 2""",
            (device["vehicle_id"],),
        ).fetchall()
        if len(trips) > 1:
            raise HTTPException(status_code=409, detail="Multiple active trips exist for this vehicle.")
        if not trips:
            return {"state": "waiting", "device_id": device["device_id"],
                    "vehicle_id": device["vehicle_id"], "door_id": device["door_id"]}
        trip = dict(trips[0])
        trip["stages"] = [dict(row) for row in connection.execute(
            """SELECT stage_id, name, stage_order FROM route_stages
               WHERE route_id = ? ORDER BY stage_order""",
            (trip["route_id"],),
        ).fetchall()]
    return {"state": "active_trip", "device_id": device["device_id"],
            "vehicle_id": device["vehicle_id"], "door_id": device["door_id"], "trip": trip}


@router.post("/session")
def create_device_session(request: DeviceSessionRequest):
    """Exchange a provisioned device credential for a trip-scoped session."""
    with db() as connection:
        device = _authenticated_device(connection, request.device_id, request.device_token)

        trip = connection.execute(
            "SELECT trip_id, vehicle_id, status FROM trips WHERE trip_id = ?",
            (request.trip_id,),
        ).fetchone()
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found.")
        if trip["status"] != "active":
            raise HTTPException(status_code=409, detail="Trip is not active.")
        if trip["vehicle_id"] != device["vehicle_id"]:
            raise HTTPException(status_code=409, detail="Device is assigned to another vehicle.")

        token, expires = issue_camera_session(connection, request.device_id, request.trip_id)

    return {
        "trip_id": request.trip_id,
        "device_id": request.device_id,
        "vehicle_id": device["vehicle_id"],
        "door_id": device["door_id"],
        "session_token": token,
        "expires_at": expires.isoformat(),
    }


def require_camera_session(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Camera session required.")
    raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Camera session required.")
    with closing(db()) as connection:
        row = connection.execute(
            """SELECT s.*, d.vehicle_id, d.door_id, d.organization_id, d.active
               FROM camera_sessions s JOIN camera_devices d ON d.device_id = s.device_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND s.ended_at IS NULL AND d.active = 1""",
            (token_hash(raw_token), now().isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Camera session expired or invalid.")
    return row
