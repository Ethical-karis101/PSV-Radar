import sqlite3
from contextlib import closing
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from backend.database import DATABASE_PATH
from backend.journeys import KENYA_TIME, event_time

router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.get("/weekly")
def weekly_trend(vehicle_id: str, end_day: date):
    if end_day.toordinal() < 7:
        raise HTTPException(status_code=422, detail="Select a later end date.")

    days = {
        end_day - timedelta(days=offset): {
            "boardings": 0,
            "alightings": 0,
            "completed_journeys": 0,
            "expected_revenue_kes": 0,
        }
        for offset in range(6, -1, -1)
    }

    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        rows = connection.execute(
            """
            SELECT event_type, occurred_at, NULL AS fare_kes
            FROM passenger_events
            WHERE vehicle_id = ?
            UNION ALL
            SELECT 'journey', alighting.occurred_at, journey.fare_kes
            FROM completed_journeys AS journey
            JOIN passenger_events AS alighting
                ON alighting.event_id = journey.alighting_event_id
            WHERE journey.vehicle_id = ?
            """,
            (vehicle_id, vehicle_id),
        )

        for event_type, occurred_at, fare_kes in rows:
            local_day = event_time(occurred_at).astimezone(KENYA_TIME).date()
            summary = days.get(local_day)
            if summary is None:
                continue

            if event_type == "journey":
                summary["completed_journeys"] += 1
                summary["expected_revenue_kes"] += fare_kes
            elif event_type == "boarding":
                summary["boardings"] += 1
            else:
                summary["alightings"] += 1

    return {
        "vehicle_id": vehicle_id,
        "days": [{"day": day.isoformat(), **summary} for day, summary in days.items()],
    }
