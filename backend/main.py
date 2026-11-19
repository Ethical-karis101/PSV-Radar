import sqlite3
import os
from contextlib import closing
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.database import DATABASE_PATH, initialize_database, save_event

from backend.fare_routes import router as fare_router
from backend.journey_routes import router as journey_router
from backend.revenue_routes import router as revenue_router
from backend.trend_routes import router as trend_router
from backend.operations import attempt_match, router as operations_router
from backend.auth import router as auth_router
from backend.device_auth import require_camera_session, router as device_auth_router

app = FastAPI(title="PSV-Radar")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "PSV_RADAR_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(fare_router)
app.include_router(journey_router)
app.include_router(revenue_router)
app.include_router(trend_router)
app.include_router(operations_router)
app.include_router(auth_router)
app.include_router(device_auth_router)
KENYA_TIME = ZoneInfo("Africa/Nairobi")

initialize_database()


class PassengerEvent(BaseModel):
    event_id: str
    vehicle_id: str
    event_type: Literal["boarding", "alighting"]
    occurred_at: datetime
    track_id: str | None = None
    trip_id: str | None = None
    route_id: str | None = None
    stage_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    door_id: str | None = Field(default=None, max_length=80)
    source: Literal["camera", "conductor", "import", "legacy"] = "legacy"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events/validate")
def validate_event(event: PassengerEvent, authorization: str | None = Header(default=None)):
    if event.source == "camera":
        session = require_camera_session(authorization)
        if session["trip_id"] != event.trip_id or session["vehicle_id"] != event.vehicle_id:
            raise HTTPException(403, "Camera event does not belong to this session.")
    return {"valid": True, "event_id": event.event_id}


@app.post("/events", status_code=201)
def create_event(event: PassengerEvent, response: Response, authorization: str | None = Header(default=None)):
    camera_session = None
    if event.source == "camera":
        camera_session = require_camera_session(authorization)
        if camera_session["trip_id"] != event.trip_id or camera_session["vehicle_id"] != event.vehicle_id:
            raise HTTPException(403, "Camera event does not belong to this session.")
        if event.door_id and event.door_id != camera_session["door_id"]:
            raise HTTPException(403, "Camera event door does not match this session.")
    result = save_event(
        event.event_id,
        event.vehicle_id,
        event.event_type,
        event.occurred_at.isoformat(),
        event.track_id,
        event.trip_id,
        event.route_id,
        event.stage_id,
        event.confidence,
        event.door_id,
        event.source,
    )

    if result == "conflict":
        raise HTTPException(
            status_code=409,
            detail="This event_id is already used by a different event.",
        )

    if result == "already_saved":
        response.status_code = 200

    journey = attempt_match(event.event_id) if result in ("saved", "already_saved") else None
    return {"status": result, "event_id": event.event_id, "journey": journey}


@app.get("/events")
def list_events():
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT event_id, vehicle_id, event_type, occurred_at,
                   track_id, trip_id, route_id, stage_id, confidence, door_id, source
            FROM passenger_events
            ORDER BY rowid DESC
            LIMIT 50
            """
        ).fetchall()

    return {"events": [dict(row) for row in rows]}


@app.get("/events/summary")
def daily_summary(vehicle_id: str, day: date):
    counts = {"boarding": 0, "alighting": 0}

    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        rows = connection.execute(
            """
            SELECT event_type, occurred_at
            FROM passenger_events
            WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        )

        for event_type, occurred_at in rows:
            event_time = datetime.fromisoformat(occurred_at)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=KENYA_TIME)

            if event_time.astimezone(KENYA_TIME).date() == day:
                counts[event_type] += 1

    return {
        "vehicle_id": vehicle_id,
        "day": day.isoformat(),
        "boardings": counts["boarding"],
        "alightings": counts["alighting"],
    }


# Serve the compiled React shell when the backend is deployed as one service.
# Imported last: the "/" mount must come after every API route, or it shadows them.
from backend import dashboard as _dashboard  # noqa: E402,F401
