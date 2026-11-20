"""Operational APIs for routes, trips, matching, reviews and close-out."""

import sqlite3
import secrets
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import DATABASE_PATH
from backend.fares import calculate_fare
from backend.auth import current_user, require_owner
from backend.device_auth import db as device_db, issue_camera_session, token_hash

router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(current_user)])


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _authorized_trip(connection, trip_id, user):
    trip = connection.execute(
        """SELECT t.*, c.user_id AS conductor_user_id, cu.organization_id AS conductor_organization_id
           FROM trips t LEFT JOIN conductors c ON c.conductor_id = t.conductor_id
           LEFT JOIN users cu ON cu.user_id = c.user_id WHERE t.trip_id = ?""",
        (trip_id,),
    ).fetchone()
    if trip is None:
        raise HTTPException(404, "Trip not found.")
    if user["role"] == "conductor":
        if trip["conductor_user_id"] != user["user_id"]:
            raise HTTPException(403, "This trip is not assigned to you.")
    elif trip["conductor_organization_id"] is not None:
        if trip["conductor_organization_id"] != user["organization_id"]:
            raise HTTPException(403, "This trip belongs to another organization.")
    else:
        device = connection.execute(
            "SELECT 1 FROM camera_devices WHERE vehicle_id = ? AND organization_id = ? LIMIT 1",
            (trip["vehicle_id"], user["organization_id"]),
        ).fetchone()
        if device is None:
            raise HTTPException(403, "This trip is outside your organization.")
    return trip


class Stage(BaseModel):
    stage_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class FareRule(BaseModel):
    boarding_stage: str
    alighting_stage: str
    fare_kes: int = Field(ge=0)


class RouteRequest(BaseModel):
    route_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    stages: list[Stage] = Field(min_length=2)
    fares: list[FareRule] = Field(default_factory=list)


class VehicleRequest(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=80)
    registration: str = Field(min_length=1, max_length=30)
    route_id: str | None = None


class ConductorRequest(BaseModel):
    conductor_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None


class TripRequest(BaseModel):
    trip_id: str = Field(min_length=1, max_length=80)
    vehicle_id: str
    route_id: str
    direction: str = Field(pattern="^(outbound|return)$")
    conductor_id: str | None = None


class TripStageRequest(BaseModel):
    stage_id: str = Field(min_length=1, max_length=80)


class CameraDeviceRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    vehicle_id: str
    door_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class CameraSessionRequest(BaseModel):
    device_id: str


class DeclarationRequest(BaseModel):
    cash_kes: int = Field(default=0, ge=0)
    mpesa_kes: int = Field(default=0, ge=0)
    other_kes: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class ReviewResolution(BaseModel):
    status: str = Field(pattern="^(resolved|excluded)$")
    note: str | None = Field(default=None, max_length=500)


@router.post("/routes", status_code=201, dependencies=[Depends(require_owner)])
def create_route(request: RouteRequest):
    if len({stage.stage_id for stage in request.stages}) != len(request.stages):
        raise HTTPException(422, "Route stages must have unique IDs.")
    if any(rule.boarding_stage == rule.alighting_stage for rule in request.fares):
        raise HTTPException(422, "Boarding and alighting stages must differ.")
    with db() as connection:
        try:
            connection.execute("INSERT INTO routes VALUES (?, ?, ?, ?, 1, ?)",
                               (request.route_id, request.name, request.origin,
                                request.destination, now()))
            connection.executemany(
                "INSERT INTO route_stages VALUES (?, ?, ?, ?)",
                [(request.route_id, stage.stage_id, stage.name, order)
                 for order, stage in enumerate(request.stages)],
            )
            connection.executemany(
                "INSERT INTO fare_rules VALUES (?, ?, ?, ?, ?)",
                [(request.route_id, rule.boarding_stage, rule.alighting_stage,
                  rule.fare_kes, now()) for rule in request.fares],
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Route or route stage already exists.") from error
    return {"route_id": request.route_id, "status": "created"}


@router.get("/routes")
def list_routes():
    with closing(db()) as connection:
        rows = connection.execute(
            "SELECT route_id, name, origin, destination, active FROM routes ORDER BY name"
        ).fetchall()
        result = []
        for row in rows:
            stages = connection.execute(
                "SELECT stage_id, name, stage_order FROM route_stages WHERE route_id = ? ORDER BY stage_order",
                (row["route_id"],),
            ).fetchall()
            result.append({**dict(row), "stages": [dict(stage) for stage in stages]})
    return {"routes": result}


@router.post("/vehicles", status_code=201, dependencies=[Depends(require_owner)])
def create_vehicle(request: VehicleRequest):
    with db() as connection:
        try:
            connection.execute(
                "INSERT INTO vehicles VALUES (?, ?, ?, 1, ?)",
                (request.vehicle_id, request.registration, request.route_id, now()),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Vehicle ID or registration already exists.") from error
    return {"vehicle_id": request.vehicle_id, "status": "created"}


@router.get("/vehicles")
def list_vehicles():
    with closing(db()) as connection:
        rows = connection.execute(
            """SELECT v.vehicle_id, v.registration, v.route_id, v.active, r.name AS route_name
               FROM vehicles v LEFT JOIN routes r ON r.route_id = v.route_id ORDER BY v.registration"""
        ).fetchall()
    return {"vehicles": [dict(row) for row in rows]}


@router.post("/conductors", status_code=201, dependencies=[Depends(require_owner)])
def create_conductor(request: ConductorRequest):
    with db() as connection:
        try:
            connection.execute("INSERT INTO conductors (conductor_id, name, phone, active, created_at) VALUES (?, ?, ?, 1, ?)",
                               (request.conductor_id, request.name, request.phone, now()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Conductor ID already exists.") from error
    return {"conductor_id": request.conductor_id, "status": "created"}


@router.get("/conductors")
def list_conductors():
    with closing(db()) as connection:
        rows = connection.execute(
            "SELECT conductor_id, name, phone, active FROM conductors ORDER BY name"
        ).fetchall()
    return {"conductors": [dict(row) for row in rows]}


@router.get("/trip-options")
def trip_options(user=Depends(current_user)):
    with closing(db()) as connection:
        if user["role"] != "conductor":
            raise HTTPException(403, "Trip setup is available from a conductor account.")
        conductor = connection.execute(
            "SELECT conductor_id FROM conductors WHERE user_id = ? AND active = 1",
            (user["user_id"],),
        ).fetchone()
        if conductor is None:
            raise HTTPException(403, "Your conductor profile is not active. Contact the PSV owner.")
        rows = connection.execute(
            """SELECT DISTINCT v.vehicle_id, v.registration, r.route_id, r.name AS route_name,
                      r.origin, r.destination
               FROM camera_devices d JOIN vehicles v ON v.vehicle_id = d.vehicle_id
               JOIN routes r ON r.route_id = v.route_id
               WHERE d.organization_id = ? AND d.active = 1 AND v.active = 1 AND r.active = 1
                 AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.vehicle_id = v.vehicle_id
                                 AND t.status IN ('scheduled', 'active'))
               ORDER BY v.registration""",
            (user["organization_id"],),
        ).fetchall()
    return {"vehicles": [dict(row) for row in rows]}


@router.post("/trips", status_code=201)
def create_trip(request: TripRequest, user=Depends(current_user)):
    with db() as connection:
        conductor_id = request.conductor_id
        if user["role"] == "conductor":
            connection.execute("BEGIN IMMEDIATE")
            conductor = connection.execute(
                "SELECT conductor_id FROM conductors WHERE user_id = ? AND active = 1",
                (user["user_id"],),
            ).fetchone()
            if conductor is None:
                raise HTTPException(403, "Your conductor profile is not active. Contact the PSV owner.")
            conductor_id = conductor["conductor_id"]
            vehicle = connection.execute(
                """SELECT v.route_id FROM vehicles v JOIN camera_devices d ON d.vehicle_id = v.vehicle_id
                   JOIN routes r ON r.route_id = v.route_id
                   WHERE v.vehicle_id = ? AND v.active = 1 AND r.active = 1
                     AND d.organization_id = ? AND d.active = 1""",
                (request.vehicle_id, user["organization_id"]),
            ).fetchone()
            if vehicle is None or vehicle["route_id"] != request.route_id:
                raise HTTPException(403, "Choose a vehicle and route prepared for your operation.")
            conflict = connection.execute(
                """SELECT 1 FROM trips WHERE status IN ('scheduled', 'active')
                   AND (conductor_id = ? OR vehicle_id = ?) LIMIT 1""",
                (conductor_id, request.vehicle_id),
            ).fetchone()
            if conflict:
                raise HTTPException(409, "You or this vehicle already have an open trip.")
        elif conductor_id:
            assignment = connection.execute(
                """SELECT 1 FROM conductors c JOIN users u ON u.user_id = c.user_id
                   WHERE c.conductor_id = ? AND u.organization_id = ? AND c.active = 1""",
                (conductor_id, user["organization_id"]),
            ).fetchone()
            if assignment is None:
                raise HTTPException(403, "The selected conductor is outside your organization or inactive.")
        if user["role"] == "owner":
            vehicle = connection.execute(
                """SELECT v.route_id FROM vehicles v JOIN camera_devices d ON d.vehicle_id = v.vehicle_id
                   WHERE v.vehicle_id = ? AND v.active = 1 AND d.organization_id = ? AND d.active = 1""",
                (request.vehicle_id, user["organization_id"]),
            ).fetchone()
            if vehicle is None or vehicle["route_id"] != request.route_id:
                raise HTTPException(403, "Choose a vehicle and route prepared for your operation.")
        stage_order = "ASC" if request.direction == "outbound" else "DESC"
        initial_stage = connection.execute(
            f"SELECT stage_id FROM route_stages WHERE route_id = ? ORDER BY stage_order {stage_order} LIMIT 1",
            (request.route_id,),
        ).fetchone()
        if initial_stage is None:
            raise HTTPException(422, "The selected route has no stages configured.")
        try:
            connection.execute(
                """INSERT INTO trips
                   (trip_id, vehicle_id, route_id, direction, conductor_id, status,
                    started_at, ended_at, created_at, current_stage_id)
                   VALUES (?, ?, ?, ?, ?, 'scheduled', NULL, NULL, ?, ?)""",
                (request.trip_id, request.vehicle_id, request.route_id, request.direction,
                 conductor_id, now(), initial_stage["stage_id"]),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(422, "Vehicle, route, conductor, or trip is invalid.") from error
    return {"trip_id": request.trip_id, "status": "scheduled"}


@router.post("/trips/{trip_id}/start")
def start_trip(trip_id: str, user=Depends(current_user)):
    with db() as connection:
        trip = _authorized_trip(connection, trip_id, user)
        stage_order = "ASC" if trip["direction"] == "outbound" else "DESC"
        initial_stage = connection.execute(
            f"SELECT stage_id FROM route_stages WHERE route_id = ? ORDER BY stage_order {stage_order} LIMIT 1",
            (trip["route_id"],),
        ).fetchone()
        if initial_stage is None:
            raise HTTPException(409, "The trip route has no stages configured.")
        result = connection.execute(
            """UPDATE trips SET status = 'active', started_at = COALESCE(started_at, ?),
               current_stage_id = COALESCE(current_stage_id, ?) WHERE trip_id = ? AND status = 'scheduled'""",
            (now(), initial_stage["stage_id"], trip_id),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Trip does not exist or is not scheduled.")
    return {"trip_id": trip_id, "status": "active"}


@router.put("/trips/{trip_id}/stage")
def update_trip_stage(trip_id: str, request: TripStageRequest, user=Depends(current_user)):
    with db() as connection:
        trip = _authorized_trip(connection, trip_id, user)
        if trip["status"] != "active":
            raise HTTPException(409, "The current stage can only be changed during an active trip.")
        stage = connection.execute(
            "SELECT stage_id, name FROM route_stages WHERE route_id = ? AND stage_id = ?",
            (trip["route_id"], request.stage_id),
        ).fetchone()
        if stage is None:
            raise HTTPException(422, "Choose a stage on this trip's route.")
        connection.execute(
            "UPDATE trips SET current_stage_id = ? WHERE trip_id = ? AND status = 'active'",
            (stage["stage_id"], trip_id),
        )
    return {"trip_id": trip_id, "current_stage_id": stage["stage_id"], "current_stage_name": stage["name"]}


@router.post("/devices", status_code=201)
def create_camera_device(request: CameraDeviceRequest, owner=Depends(require_owner)):
    raw_token = secrets.token_urlsafe(48)
    with device_db() as connection:
        try:
            connection.execute(
                "INSERT INTO camera_devices VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (request.device_id, owner["organization_id"], request.vehicle_id,
                 request.door_id, request.name, token_hash(raw_token), now()),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Device ID already exists or vehicle is invalid.") from error
    return {"device_id": request.device_id, "status": "created", "device_token": raw_token,
            "warning": "Store this token securely; it will not be shown again."}


@router.get("/devices")
def list_camera_devices(user=Depends(current_user)):
    with closing(device_db()) as connection:
        rows = connection.execute(
            """SELECT device_id, vehicle_id, door_id, name, active, created_at
               FROM camera_devices WHERE organization_id = ? ORDER BY created_at DESC""",
            (user["organization_id"],),
        ).fetchall()
    return {"devices": [dict(row) for row in rows]}


@router.post("/trips/{trip_id}/camera-session")
def create_camera_session(trip_id: str, request: CameraSessionRequest, user=Depends(current_user)):
    with device_db() as connection:
        trip = connection.execute(
            """SELECT t.*, c.user_id AS conductor_user_id FROM trips t
               LEFT JOIN conductors c ON c.conductor_id = t.conductor_id WHERE t.trip_id = ?""",
            (trip_id,),
        ).fetchone()
        device = connection.execute(
            "SELECT * FROM camera_devices WHERE device_id = ? AND active = 1", (request.device_id,)
        ).fetchone()
        if trip is None or device is None:
            raise HTTPException(404, "Trip or camera device not found.")
        if user["role"] == "conductor" and trip["conductor_user_id"] != user["user_id"]:
            raise HTTPException(403, "This trip is not assigned to you.")
        if device["organization_id"] != user["organization_id"]:
            raise HTTPException(403, "Camera device belongs to another organization.")
        if device["vehicle_id"] != trip["vehicle_id"]:
            raise HTTPException(409, "Camera device is assigned to another vehicle.")
        if trip["status"] != "active":
            raise HTTPException(409, "Start the trip before starting its camera session.")
        token, expires = issue_camera_session(connection, request.device_id, trip_id)
    return {"trip_id": trip_id, "device_id": request.device_id, "door_id": device["door_id"],
            "session_token": token, "expires_at": expires.isoformat()}


@router.post("/trips/{trip_id}/end")
def end_trip(trip_id: str, user=Depends(current_user)):
    with db() as connection:
        trip = _authorized_trip(connection, trip_id, user)
        if trip["status"] not in ("active", "scheduled"):
            raise HTTPException(409, "Trip has already ended.")
        connection.execute("UPDATE trips SET status = 'ended', ended_at = ? WHERE trip_id = ?", (now(), trip_id))
        unmatched = connection.execute(
            """SELECT event_id FROM passenger_events e
               WHERE e.trip_id = ? AND e.event_type = 'boarding'
                 AND NOT EXISTS (SELECT 1 FROM completed_journeys j WHERE j.boarding_event_id = e.event_id)""",
            (trip_id,),
        ).fetchall()
        for event in unmatched:
            _create_review(connection, trip_id, event["event_id"], "Passenger has no matching alighting event")
    return {"trip_id": trip_id, "status": "ended", "open_review_cases": len(unmatched)}


@router.get("/trips")
def list_trips(status: str | None = Query(default=None), user=Depends(current_user)):
    query = """SELECT t.*, v.registration, r.name AS route_name, c.name AS conductor_name,
                      COALESCE((SELECT SUM(j.fare_kes) FROM completed_journeys j WHERE j.trip_id = t.trip_id), 0) AS expected_revenue_kes,
                      (SELECT COUNT(*) FROM passenger_events e WHERE e.trip_id = t.trip_id AND e.event_type = 'boarding') AS boardings_count,
                      (SELECT cash_kes + mpesa_kes + other_kes FROM collection_declarations d WHERE d.trip_id = t.trip_id) AS declared_revenue_kes,
                      (SELECT name FROM route_stages s WHERE s.route_id = t.route_id AND s.stage_id = t.current_stage_id) AS current_stage_name
               FROM trips t JOIN vehicles v ON v.vehicle_id = t.vehicle_id
               JOIN routes r ON r.route_id = t.route_id LEFT JOIN conductors c ON c.conductor_id = t.conductor_id"""
    conditions = []
    params = []
    if status:
        conditions.append("t.status = ?")
        params.append(status)
    if user["role"] == "conductor":
        conditions.append("c.user_id = ?")
        params.append(user["user_id"])
    else:
        conditions.append("(cu.organization_id = ? OR (cu.organization_id IS NULL AND EXISTS (SELECT 1 FROM camera_devices cd WHERE cd.vehicle_id = t.vehicle_id AND cd.organization_id = ?)))")
        params.extend((user["organization_id"], user["organization_id"]))
    query = query.replace("LEFT JOIN conductors c ON c.conductor_id = t.conductor_id", "LEFT JOIN conductors c ON c.conductor_id = t.conductor_id LEFT JOIN users cu ON cu.user_id = c.user_id")
    query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY COALESCE(t.started_at, t.created_at) DESC"
    with closing(db()) as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
        trips = []
        for row in rows:
            trip = dict(row)
            trip["stages"] = [dict(stage) for stage in connection.execute(
                "SELECT stage_id, name, stage_order FROM route_stages WHERE route_id = ? ORDER BY stage_order",
                (trip["route_id"],),
            ).fetchall()]
            trips.append(trip)
    return {"trips": trips}


def _fare(connection, route_id, boarding_stage, alighting_stage):
    row = connection.execute(
        """SELECT fare_kes FROM fare_rules WHERE route_id = ? AND boarding_stage = ?
           AND alighting_stage = ? ORDER BY effective_from DESC LIMIT 1""",
        (route_id, boarding_stage, alighting_stage),
    ).fetchone()
    if row:
        return row["fare_kes"]
    try:
        return calculate_fare(boarding_stage, alighting_stage)
    except ValueError:
        return None


def _create_review(connection, trip_id, event_id, reason, boarding_event_id=None):
    exists = connection.execute(
        "SELECT 1 FROM review_cases WHERE trip_id = ? AND event_id IS ? AND reason = ? AND status = 'open'",
        (trip_id, event_id, reason),
    ).fetchone()
    if exists:
        return
    connection.execute(
        "INSERT INTO review_cases VALUES (?, ?, ?, ?, ?, 'open', NULL, NULL, ?, NULL)",
        (str(uuid4()), trip_id, event_id, boarding_event_id, reason, now()),
    )


def _attempt_fifo_match(connection, event):
    """Pair camera crossings by trip order when camera-local IDs differ.

    A door tracker ID only lasts while a person is visible near the door. It
    is therefore not safe to require the same ID for boarding and alighting.
    FIFO is the conservative MVP fallback; uncertain cases stay reviewable.
    """
    if not event["trip_id"] or not event["stage_id"]:
        return None

    if event["event_type"] == "alighting":
        candidate = connection.execute(
            """SELECT * FROM passenger_events e WHERE e.trip_id = ? AND e.vehicle_id = ?
               AND e.event_type = 'boarding' AND e.stage_id IS NOT NULL
               AND e.occurred_at < ?
               AND NOT EXISTS (SELECT 1 FROM completed_journeys j
                              WHERE j.boarding_event_id = e.event_id OR j.alighting_event_id = e.event_id)
               ORDER BY e.occurred_at ASC LIMIT 1""",
            (event["trip_id"], event["vehicle_id"], event["occurred_at"]),
        ).fetchone()
        boarding, alighting = candidate, event
    else:
        candidate = connection.execute(
            """SELECT * FROM passenger_events e WHERE e.trip_id = ? AND e.vehicle_id = ?
               AND e.event_type = 'alighting' AND e.stage_id IS NOT NULL
               AND e.occurred_at > ?
               AND NOT EXISTS (SELECT 1 FROM completed_journeys j
                              WHERE j.boarding_event_id = e.event_id OR j.alighting_event_id = e.event_id)
               ORDER BY e.occurred_at ASC LIMIT 1""",
            (event["trip_id"], event["vehicle_id"], event["occurred_at"]),
        ).fetchone()
        boarding, alighting = event, candidate

    if candidate is None:
        if event["event_type"] == "alighting":
            _create_review(connection, event["trip_id"], event["event_id"], "Alighting has no matching boarding event")
        return None

    fare = _fare(connection, event["route_id"], boarding["stage_id"], alighting["stage_id"])
    if fare is None:
        _create_review(connection, event["trip_id"], event["event_id"], "No fare configured for these stages", boarding["event_id"])
        return None

    confidence_values = [value for value in (boarding["confidence"], alighting["confidence"]) if value is not None]
    confidence = min(confidence_values, default=0.65)
    try:
        connection.execute(
            """INSERT INTO completed_journeys
               (boarding_event_id, alighting_event_id, vehicle_id, boarding_stage,
                alighting_stage, fare_kes, trip_id, track_id, confidence, status,
                created_at, match_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'fifo_occupancy')""",
            (boarding["event_id"], alighting["event_id"], event["vehicle_id"],
             boarding["stage_id"], alighting["stage_id"], fare, event["trip_id"],
             event["track_id"], confidence, now()),
        )
    except sqlite3.IntegrityError:
        return None
    return {"boarding_event_id": boarding["event_id"], "alighting_event_id": alighting["event_id"],
            "fare_kes": fare, "match_method": "fifo_occupancy", "confidence": confidence}


def attempt_match(event_id):
    with db() as connection:
        event = connection.execute("SELECT * FROM passenger_events WHERE event_id = ?", (event_id,)).fetchone()
        if not event or not event["trip_id"] or not event["stage_id"]:
            return None
        opposite = "boarding" if event["event_type"] == "alighting" else "alighting"
        candidate = connection.execute(
            """SELECT * FROM passenger_events e WHERE e.track_id = ? AND e.trip_id = ?
               AND e.vehicle_id = ? AND e.event_type = ?
               AND NOT EXISTS (SELECT 1 FROM completed_journeys j
                              WHERE j.boarding_event_id = e.event_id OR j.alighting_event_id = e.event_id)
               ORDER BY e.occurred_at DESC LIMIT 1""",
            (event["track_id"], event["trip_id"], event["vehicle_id"], opposite),
        ).fetchone()
        if not candidate:
            return _attempt_fifo_match(connection, event)
        boarding = candidate if candidate["event_type"] == "boarding" else event
        alighting = event if event["event_type"] == "alighting" else candidate
        if alighting["occurred_at"] <= boarding["occurred_at"]:
            _create_review(connection, event["trip_id"], event_id, "Events are out of chronological order")
            return None
        fare = _fare(connection, event["route_id"], boarding["stage_id"], alighting["stage_id"])
        if fare is None:
            _create_review(connection, event["trip_id"], event_id, "No fare configured for these stages", boarding["event_id"])
            return None
        try:
            connection.execute(
                """INSERT INTO completed_journeys
                   (boarding_event_id, alighting_event_id, vehicle_id, boarding_stage,
                   alighting_stage, fare_kes, trip_id, track_id, confidence, status, created_at, match_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'explicit_track')""",
                (boarding["event_id"], alighting["event_id"], event["vehicle_id"],
                 boarding["stage_id"], alighting["stage_id"], fare, event["trip_id"],
                 event["track_id"], min(filter(None, (event["confidence"], candidate["confidence"])), default=None), now()),
            )
        except sqlite3.IntegrityError:
            return None
        connection.execute(
            """UPDATE review_cases SET status = 'resolved', resolution = 'auto_matched',
               resolved_at = ? WHERE status = 'open' AND
               (event_id IN (?, ?) OR journey_boarding_event_id IN (?, ?))""",
            (now(), boarding["event_id"], alighting["event_id"],
             boarding["event_id"], alighting["event_id"]),
        )
        return {"boarding_event_id": boarding["event_id"], "alighting_event_id": alighting["event_id"], "fare_kes": fare}


@router.get("/reviews")
def list_reviews(status: str = Query(default="open", pattern="^(open|resolved|excluded|all)$")):
    query = """SELECT rc.*, e.event_type, e.occurred_at, t.vehicle_id, t.route_id,
                      v.registration, r.name AS route_name
               FROM review_cases rc LEFT JOIN passenger_events e ON e.event_id = rc.event_id
               LEFT JOIN trips t ON t.trip_id = rc.trip_id LEFT JOIN vehicles v ON v.vehicle_id = t.vehicle_id
               LEFT JOIN routes r ON r.route_id = t.route_id"""
    params = ()
    if status != "all":
        query += " WHERE rc.status = ?"
        params = (status,)
    query += " ORDER BY rc.created_at DESC"
    with closing(db()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"reviews": [dict(row) for row in rows]}


@router.post("/reviews/{case_id}/resolve", dependencies=[Depends(require_owner)])
def resolve_review(case_id: str, request: ReviewResolution):
    with db() as connection:
        result = connection.execute(
            "UPDATE review_cases SET status = ?, resolution = ?, note = ?, resolved_at = ? WHERE case_id = ? AND status = 'open'",
            (request.status, request.status, request.note, now(), case_id),
        )
        if result.rowcount != 1:
            raise HTTPException(404, "Open review case not found.")
    return {"case_id": case_id, "status": request.status}


@router.put("/trips/{trip_id}/declaration")
def declare_collection(trip_id: str, request: DeclarationRequest, user=Depends(current_user)):
    with db() as connection:
        trip = _authorized_trip(connection, trip_id, user)
        if trip["status"] not in ("active", "ended"):
            raise HTTPException(409, "Only an active or ended trip can be closed out.")
        if trip["status"] == "active":
            connection.execute("UPDATE trips SET status = 'ended', ended_at = ? WHERE trip_id = ?", (now(), trip_id))
            unmatched = connection.execute(
                """SELECT event_id FROM passenger_events e WHERE e.trip_id = ? AND e.event_type = 'boarding'
                   AND NOT EXISTS (SELECT 1 FROM completed_journeys j WHERE j.boarding_event_id = e.event_id)""",
                (trip_id,),
            ).fetchall()
            for event in unmatched:
                _create_review(connection, trip_id, event["event_id"], "Passenger has no matching alighting event")
        connection.execute(
            """INSERT INTO collection_declarations VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(trip_id) DO UPDATE SET cash_kes = excluded.cash_kes,
                 mpesa_kes = excluded.mpesa_kes, other_kes = excluded.other_kes,
                 notes = excluded.notes, submitted_at = excluded.submitted_at""",
            (trip_id, request.cash_kes, request.mpesa_kes, request.other_kes, request.notes, now()),
        )
    return {"trip_id": trip_id, "status": "ended", "declared_revenue_kes": request.cash_kes + request.mpesa_kes + request.other_kes}


@router.get("/summary")
def summary():
    with closing(db()) as connection:
        totals = connection.execute(
            """SELECT COUNT(*) AS trips, COALESCE(SUM(expected), 0) AS expected,
                      COALESCE(SUM(declared), 0) AS declared FROM (
                SELECT t.trip_id,
                  (SELECT SUM(fare_kes) FROM completed_journeys j WHERE j.trip_id = t.trip_id) expected,
                  (SELECT cash_kes + mpesa_kes + other_kes FROM collection_declarations d WHERE d.trip_id = t.trip_id) declared
                FROM trips t WHERE t.status IN ('ended', 'reconciled'))"""
        ).fetchone()
        reviews = connection.execute("SELECT COUNT(*) AS count FROM review_cases WHERE status = 'open'").fetchone()["count"]
        passengers = connection.execute(
            "SELECT COUNT(*) AS count FROM passenger_events WHERE event_type = 'boarding'"
        ).fetchone()["count"]
    return {"trips": totals["trips"], "expected_revenue_kes": totals["expected"],
            "declared_revenue_kes": totals["declared"], "variance_kes": totals["declared"] - totals["expected"],
            "open_review_cases": reviews, "boardings": passengers}
