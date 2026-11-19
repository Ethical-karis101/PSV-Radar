import sqlite3
import os
from contextlib import closing
from pathlib import Path

DATABASE_PATH = Path(os.getenv(
    "PSV_RADAR_DATABASE_PATH",
    str(Path(__file__).resolve().with_name("passenger_events.sqlite3")),
))


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS passenger_events (
                    event_id TEXT NOT NULL PRIMARY KEY,
                    vehicle_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN ('boarding', 'alighting')),
                    occurred_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_journeys (
                    boarding_event_id TEXT NOT NULL PRIMARY KEY,
                    alighting_event_id TEXT NOT NULL UNIQUE,
                    vehicle_id TEXT NOT NULL,
                    boarding_stage TEXT NOT NULL,
                    alighting_stage TEXT NOT NULL,
                    fare_kes INTEGER NOT NULL CHECK (fare_kes >= 0)
                )
                """
            )

            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(passenger_events)")
            }
            for name, definition in (
                ("track_id", "TEXT"), ("trip_id", "TEXT"), ("route_id", "TEXT"),
                ("stage_id", "TEXT"), ("confidence", "REAL"), ("door_id", "TEXT"),
                ("source", "TEXT NOT NULL DEFAULT 'legacy'"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE passenger_events ADD COLUMN {name} {definition}")

            journey_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(completed_journeys)")
            }
            for name, definition in (
                ("trip_id", "TEXT"), ("track_id", "TEXT"),
                ("confidence", "REAL"), ("status", "TEXT NOT NULL DEFAULT 'confirmed'"),
                ("created_at", "TEXT"), ("match_method", "TEXT NOT NULL DEFAULT 'legacy'"),
            ):
                if name not in journey_columns:
                    connection.execute(f"ALTER TABLE completed_journeys ADD COLUMN {name} {definition}")

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY, name TEXT NOT NULL, origin TEXT NOT NULL,
                    destination TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS route_stages (
                    route_id TEXT NOT NULL REFERENCES routes(route_id), stage_id TEXT NOT NULL,
                    name TEXT NOT NULL, stage_order INTEGER NOT NULL CHECK (stage_order >= 0),
                    PRIMARY KEY (route_id, stage_id), UNIQUE (route_id, stage_order)
                );
                CREATE TABLE IF NOT EXISTS fare_rules (
                    route_id TEXT NOT NULL REFERENCES routes(route_id), boarding_stage TEXT NOT NULL,
                    alighting_stage TEXT NOT NULL, fare_kes INTEGER NOT NULL CHECK (fare_kes >= 0),
                    effective_from TEXT NOT NULL,
                    PRIMARY KEY (route_id, boarding_stage, alighting_stage, effective_from)
                );
                CREATE TABLE IF NOT EXISTS vehicles (
                    vehicle_id TEXT PRIMARY KEY, registration TEXT NOT NULL UNIQUE,
                    route_id TEXT REFERENCES routes(route_id), active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conductors (
                    conductor_id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trips (
                    trip_id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id),
                    route_id TEXT NOT NULL REFERENCES routes(route_id),
                    direction TEXT NOT NULL CHECK (direction IN ('outbound', 'return')),
                    conductor_id TEXT REFERENCES conductors(conductor_id),
                    status TEXT NOT NULL CHECK (status IN ('scheduled', 'active', 'ended', 'reconciled')),
                    started_at TEXT, ended_at TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_cases (
                    case_id TEXT PRIMARY KEY, trip_id TEXT REFERENCES trips(trip_id),
                    event_id TEXT REFERENCES passenger_events(event_id), journey_boarding_event_id TEXT,
                    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'resolved', 'excluded')),
                    resolution TEXT, note TEXT, created_at TEXT NOT NULL, resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS collection_declarations (
                    trip_id TEXT PRIMARY KEY REFERENCES trips(trip_id), cash_kes INTEGER NOT NULL DEFAULT 0 CHECK (cash_kes >= 0),
                    mpesa_kes INTEGER NOT NULL DEFAULT 0 CHECK (mpesa_kes >= 0),
                    other_kes INTEGER NOT NULL DEFAULT 0 CHECK (other_kes >= 0), notes TEXT, submitted_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    organization_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
                    name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('owner', 'conductor')), active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS camera_devices (
                    device_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
                    vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id), door_id TEXT NOT NULL,
                    name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS camera_sessions (
                    session_id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES camera_devices(device_id),
                    trip_id TEXT NOT NULL REFERENCES trips(trip_id), token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT
                );
                """
            )
            conductor_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(conductors)")
            }
            if "user_id" not in conductor_columns:
                connection.execute("ALTER TABLE conductors ADD COLUMN user_id TEXT")


def save_event(event_id, vehicle_id, event_type, occurred_at, track_id=None,
               trip_id=None, route_id=None, stage_id=None, confidence=None,
               door_id=None, source="legacy"):
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        with connection:
            result = connection.execute(
                """
                INSERT INTO passenger_events
                    (event_id, vehicle_id, event_type, occurred_at, track_id,
                     trip_id, route_id, stage_id, confidence, door_id, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (event_id, vehicle_id, event_type, occurred_at, track_id, trip_id,
                 route_id, stage_id, confidence, door_id, source),
            )
            if result.rowcount == 1:
                return "saved"

            existing = connection.execute(
                """
                SELECT vehicle_id, event_type, occurred_at, track_id, trip_id,
                       route_id, stage_id, confidence, door_id, source
                FROM passenger_events WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            if existing == (vehicle_id, event_type, occurred_at, track_id, trip_id,
                            route_id, stage_id, confidence, door_id, source):
                return "already_saved"
            return "conflict"


if __name__ == "__main__":
    initialize_database()
    print(f"Database ready: {DATABASE_PATH}")
