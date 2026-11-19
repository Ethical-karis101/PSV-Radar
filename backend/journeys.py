import sqlite3
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.database import DATABASE_PATH
from backend.fares import calculate_fare

KENYA_TIME = ZoneInfo("Africa/Nairobi")


def event_time(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KENYA_TIME)
    return parsed


def price_journey(
    boarding_event_id: str,
    alighting_event_id: str,
    boarding_stage: str,
    alighting_stage: str,
) -> dict:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT event_id, vehicle_id, event_type, occurred_at
            FROM passenger_events
            WHERE event_id IN (?, ?)
            """,
            (boarding_event_id, alighting_event_id),
        ).fetchall()

    events = {row["event_id"]: row for row in rows}
    boarding = events.get(boarding_event_id)
    alighting = events.get(alighting_event_id)

    if boarding is None or alighting is None:
        raise ValueError("Both event IDs must refer to saved events.")

    if boarding["event_type"] != "boarding" or alighting["event_type"] != "alighting":
        raise ValueError("Provide a boarding event followed by an alighting event.")

    if boarding["vehicle_id"] != alighting["vehicle_id"]:
        raise ValueError("Both events must belong to the same vehicle.")

    if event_time(alighting["occurred_at"]) <= event_time(boarding["occurred_at"]):
        raise ValueError("The alighting must occur after the boarding.")

    return {
        "vehicle_id": boarding["vehicle_id"],
        "boarding_event_id": boarding_event_id,
        "alighting_event_id": alighting_event_id,
        "boarding_stage": boarding_stage,
        "alighting_stage": alighting_stage,
        "fare_kes": calculate_fare(boarding_stage, alighting_stage),
    }
