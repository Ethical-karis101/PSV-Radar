import sqlite3
from contextlib import closing

from backend.database import DATABASE_PATH, initialize_database
from backend.journeys import price_journey


def initialize_journey_storage():
    initialize_database()

    with closing(sqlite3.connect(DATABASE_PATH)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS completed_journeys (
                boarding_event_id TEXT NOT NULL PRIMARY KEY
                    REFERENCES passenger_events(event_id),
                alighting_event_id TEXT NOT NULL UNIQUE
                    REFERENCES passenger_events(event_id),
                vehicle_id TEXT NOT NULL,
                boarding_stage TEXT NOT NULL,
                alighting_stage TEXT NOT NULL,
                fare_kes INTEGER NOT NULL CHECK (fare_kes >= 0)
            )
            """
        )


def save_journey(boarding_event_id, alighting_event_id, boarding_stage, alighting_stage):
    journey = price_journey(
        boarding_event_id, alighting_event_id, boarding_stage, alighting_stage
    )

    with closing(sqlite3.connect(DATABASE_PATH)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        result = connection.execute(
            """
            INSERT INTO completed_journeys (
                boarding_event_id, alighting_event_id, vehicle_id,
                boarding_stage, alighting_stage, fare_kes
            )
            VALUES (
                :boarding_event_id, :alighting_event_id, :vehicle_id,
                :boarding_stage, :alighting_stage, :fare_kes
            )
            ON CONFLICT DO NOTHING
            """,
            journey,
        )

        if result.rowcount == 1:
            return {"status": "saved", **journey}

        existing = connection.execute(
            """
            SELECT boarding_stage, alighting_stage, fare_kes
            FROM completed_journeys
            WHERE boarding_event_id = ? AND alighting_event_id = ?
            """,
            (boarding_event_id, alighting_event_id),
        ).fetchone()

        if existing is not None and existing[:2] == (boarding_stage, alighting_stage):
            return {"status": "already_saved", **journey, "fare_kes": existing[2]}

        raise ValueError("One of these events already belongs to a saved journey.")
