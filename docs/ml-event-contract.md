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

Each round-trip direction should have its own `trip_id`. For this MVP, the
conductor selects the vehicle's current route stage from their own phone while
the trip is active (`PUT /operations/trips/{trip_id}/stage`). The camera app
reads that stage from `POST /device/active-trip`; it must attach the latest
`current_stage_id` to each crossing event as `stage_id`. It should refresh the
active-trip context regularly and immediately before publishing a crossing so
stage changes made by the conductor reach the camera without handling the
camera phone. This is an operator-provided stage, not GPS-derived stop
detection; the event review queue remains the safeguard for mistakes.

## Camera session authentication and Android duty flow

Camera events must use a short-lived session token. The following is the target
workflow for the dedicated Android camera app:

1. An owner provisions a device with `POST /operations/devices` and stores the returned device token securely on the camera device.
2. At the start of a shift, the dedicated Android camera app is opened and the conductor taps **Start duty** while the app is visible. The app remains in a camera foreground service while on duty.
3. The app calls `POST /device/active-trip` using its device ID and device token. The endpoint returns `waiting` when no trip is active for that vehicle, or the active trip, `current_stage_id`, `current_stage_name`, ordered route stages, and camera door when one is active.
4. An authenticated conductor creates and starts the trip from their own phone, then updates the current route stage as the vehicle progresses. The camera app polls for the active trip and exchanges its device credentials at `POST /device/session` with the discovered trip ID.
5. The edge agent sends the returned short-lived `session_token` with each camera event and refreshes it automatically when needed. After the trip ends, the app returns to waiting; it stops camera processing at end of duty.

The device credential is a long-lived secret: store it in Android Keystore-backed storage, never in a QR code that can be photographed or in routine conductor-facing screens. No video should be uploaded or retained; publish event metadata only.

The authenticated-user endpoint `POST /operations/trips/{trip_id}/camera-session` remains available for dashboard/manual testing, but operators should not copy tokens during normal camera operation.

The session is bound to the trip, vehicle, and camera door. The API rejects
events that do not match those bindings. The replayable publisher in
`edge_agent/agent.py` is the MVP integration point for a real detector.
