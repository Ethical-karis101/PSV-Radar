import sqlite3
from contextlib import closing
from datetime import date

from fastapi import APIRouter

from backend.database import DATABASE_PATH
from backend.journeys import KENYA_TIME, event_time

router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.get("/daily")
def daily_revenue(vehicle_id: str, day: date):
    completed_journeys = 0
    expected_revenue_kes = 0

    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
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

    return {
        "vehicle_id": vehicle_id,
        "day": day.isoformat(),
        "completed_journeys": completed_journeys,
        "expected_revenue_kes": expected_revenue_kes,
    }
