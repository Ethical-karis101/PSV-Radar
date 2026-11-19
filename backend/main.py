import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from backend.database import DATABASE_PATH, save_event

app = FastAPI(title="PSV-Radar")


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
