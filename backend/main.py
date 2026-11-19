import sqlite3
from contextlib import closing
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from backend.database import DATABASE_PATH, save_event

from backend.fare_routes import router as fare_router
from backend.journey_routes import router as journey_router
from backend.revenue_routes import router as revenue_router
from backend.trend_routes import router as trend_router

app = FastAPI(title="PSV-Radar")
app.include_router(fare_router)
app.include_router(journey_router)
app.include_router(revenue_router)
app.include_router(trend_router)
KENYA_TIME = ZoneInfo("Africa/Nairobi")


class PassengerEvent(BaseModel):
    event_id: str
    vehicle_id: str
    event_type: Literal["boarding", "alighting"]
    occurred_at: datetime


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events/validate")
def validate_event(event: PassengerEvent):
    return {"valid": True, "event_id": event.event_id}


@app.post("/events", status_code=201)
def create_event(event: PassengerEvent, response: Response):
    result = save_event(
        event.event_id,
        event.vehicle_id,
        event.event_type,
        event.occurred_at.isoformat(),
    )

    if result == "conflict":
        raise HTTPException(
            status_code=409,
            detail="This event_id is already used by a different event.",
        )

    if result == "already_saved":
        response.status_code = 200

    return {"status": result, "event_id": event.event_id}


@app.get("/events")
def list_events():
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT event_id, vehicle_id, event_type, occurred_at
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
