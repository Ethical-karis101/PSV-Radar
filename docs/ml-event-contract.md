# ML event handoff

## Current API

POST /events accepts event_id, vehicle_id, event_type and occurred_at. Camera events should also send `track_id`, `trip_id`, `route_id`, `stage_id`, `door_id`, `source: "camera"`, and an optional confidence score from 0 to 1.
Reuse the same event_id on retries and include a timezone in occurred_at.
An identical retry returns HTTP 200 and does not add another row.

## Proposed fields for journey pricing

- stage_id identifies the route stop. The team will agree on who assigns it.
- trip_id identifies one run of a vehicle along its route.
- track_id is a temporary reference scoped to one vehicle and trip.

Example boarding event for the proposed contract:

    {
      "event_id": "ml-trip-001-board-17",
      "vehicle_id": "psv-ml-demo",
      "event_type": "boarding",
      "occurred_at": "2026-11-19T10:15:00+03:00",
      "stage_id": "stage-a",
      "trip_id": "trip-001",
      "track_id": "17"
    }

For a confirmed alighting at stage-c, send a new event_id and reuse the
vehicle_id, trip_id and track_id. If the tracker cannot confidently link
the events, leave the journey unpaired for review.

The API now stores these fields and automatically attempts to match a
boarding and alighting event when the second event arrives. A failed match
is represented as a review case. When a trip ends, all boarding events that
remain unmatched are added to the review queue.

The camera tracker only needs to preserve `track_id` while a person is
visible at the door. It must not be assumed to identify the same passenger
for the whole trip. When camera-local IDs differ, the backend uses a
trip-scoped FIFO occupancy fallback and records `match_method:
"fifo_occupancy"`. Low-confidence or impossible cases remain reviewable.

The device or route service is responsible for mapping location to
`stage_id`. Each round-trip direction should have its own `trip_id`.

## Camera session authentication

Camera events must use a short-lived session token:

1. An owner provisions a device with `POST /operations/devices` and stores the returned device token securely on the camera device.
2. An authenticated conductor or owner starts the trip.
3. The edge agent exchanges its device ID and device token at `POST /device/session` with the trip ID.
4. The edge agent sends the returned short-lived `session_token` with each camera event and refreshes it automatically when needed.

The authenticated-user endpoint `POST /operations/trips/{trip_id}/camera-session` remains available for dashboard/manual testing, but operators should not copy tokens during normal camera operation.

The session is bound to the trip, vehicle, and camera door. The API rejects
events that do not match those bindings. The replayable publisher in
`edge_agent/agent.py` is the MVP integration point for a real detector.
