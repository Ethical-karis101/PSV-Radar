# ML event handoff

## Current API

POST /events accepts event_id, vehicle_id, event_type and occurred_at.
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

Before implementation, confirm whether the tracker can preserve track_id
between boarding and alighting and who will map the device location to
stage_id. The API does not yet store the three proposed fields.
