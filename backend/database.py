import sqlite3
from contextlib import closing
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().with_name("passenger_events.sqlite3")


def initialize_database():
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS passenger_events (
                    event_id TEXT NOT NULL PRIMARY KEY,
                    vehicle_id TEXT NOT NULL,
                    event_type TEXT NOT NULL
                        CHECK (event_type IN ('boarding', 'alighting')),
                    occurred_at TEXT NOT NULL
                )
                """
            )

def save_event(event_id, vehicle_id, event_type, occurred_at):
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            result = connection.execute(
                """
                INSERT INTO passenger_events
                    (event_id, vehicle_id, event_type, occurred_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (event_id, vehicle_id, event_type, occurred_at),
            )
            if result.rowcount == 1:
                return "saved"

            existing = connection.execute(
                """
                SELECT vehicle_id, event_type, occurred_at
                FROM passenger_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if existing == (vehicle_id, event_type, occurred_at):
                return "already_saved"

            return "conflict"
            
if __name__ == "__main__":
    initialize_database()
    print(f"Database ready: {DATABASE_PATH}")
