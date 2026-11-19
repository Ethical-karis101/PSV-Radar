import sqlite3
from contextlib import closing
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.database import DATABASE_PATH
from backend.journey_storage import initialize_journey_storage
from backend.journeys import KENYA_TIME, event_time

router = APIRouter(prefix="/revenue", tags=["revenue"])


class CollectionDeclaration(BaseModel):
    declared_collections_kes: int = Field(
        strict=True, ge=0, le=2**63 - 1
    )


def initialize_revenue_storage():
    initialize_journey_storage()

    with closing(sqlite3.connect(DATABASE_PATH)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS declared_collections (
                vehicle_id TEXT NOT NULL,
                day TEXT NOT NULL,
                declared_collections_kes INTEGER NOT NULL
                    CHECK (declared_collections_kes >= 0),
                PRIMARY KEY (vehicle_id, day)
            )
            """
        )


@router.put("/declared")
def declare_collections(
    vehicle_id: str, day: date, declaration: CollectionDeclaration
):
    amount = declaration.declared_collections_kes
    with closing(sqlite3.connect(DATABASE_PATH)) as connection, connection:
        connection.execute(
            """
            INSERT INTO declared_collections
                (vehicle_id, day, declared_collections_kes)
            VALUES (?, ?, ?)
            ON CONFLICT(vehicle_id, day) DO UPDATE SET
                declared_collections_kes = excluded.declared_collections_kes
            """,
            (vehicle_id, day.isoformat(), amount),
        )

    return {
        "vehicle_id": vehicle_id,
        "day": day.isoformat(),
        "declared_collections_kes": amount,
    }


@router.get("/daily")
def daily_revenue(vehicle_id: str, day: date):
    completed_journeys = 0
    expected_revenue_kes = 0

    with closing(sqlite3.connect(DATABASE_PATH)) as connection, connection:
        connection.execute("BEGIN")
        rows = connection.execute(
            """
            SELECT journey.fare_kes, alighting.occurred_at
            FROM completed_journeys AS journey
            JOIN passenger_events AS alighting
                ON alighting.event_id = journey.alighting_event_id
            WHERE journey.vehicle_id = ?
            """,
            (vehicle_id,),
        )

        for fare_kes, occurred_at in rows:
            local_day = event_time(occurred_at).astimezone(KENYA_TIME).date()
            if local_day == day:
                completed_journeys += 1
                expected_revenue_kes += fare_kes

        declaration = connection.execute(
            """
            SELECT declared_collections_kes
            FROM declared_collections
            WHERE vehicle_id = ? AND day = ?
            """,
            (vehicle_id, day.isoformat()),
        ).fetchone()

    declared_kes = declaration[0] if declaration is not None else None
    variance_kes = (
        declared_kes - expected_revenue_kes if declared_kes is not None else None
    )

    return {
        "vehicle_id": vehicle_id,
        "day": day.isoformat(),
        "completed_journeys": completed_journeys,
        "expected_revenue_kes": expected_revenue_kes,
        "declared_collections_kes": declared_kes,
        "variance_kes": variance_kes,
    }


if __name__ == "__main__":
    initialize_revenue_storage()
    print("Revenue storage ready.")
