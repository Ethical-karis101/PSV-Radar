# Camera MVP integration

The first camera pilot uses one mounted camera at the shared passenger door.
The camera agent detects people, tracks them only while they are visible near
the door, and emits one event when a person crosses the virtual line.

## Recommended pipeline

1. Pretrained person detector.
2. Lightweight multi-object tracker.
3. Virtual line-crossing rule for boarding/alighting direction.
4. Conductor-selected trip and stage context.
5. `POST /events` with metadata only; do not upload video in the MVP.

The tracker ID is local to the camera view. It is not a permanent passenger
identity and should not be used to join a boarding event to a later alighting
event. The backend falls back to trip-scoped FIFO occupancy matching when the
two door crossings have different local IDs.

## Event example

```json
{
  "event_id": "cam-2026-11-19-00001",
  "vehicle_id": "kda-418m",
  "trip_id": "trip-001",
  "route_id": "rongai-cbd",
  "stage_id": "stage-a",
  "event_type": "boarding",
  "occurred_at": "2026-11-19T08:30:00+03:00",
  "track_id": "door-track-17",
  "door_id": "main-door",
  "source": "camera",
  "confidence": 0.94
}
```

## Safety rules

- Store event metadata, not faces or continuous video, in the backend.
- Keep camera-local IDs scoped to a trip/device.
- Keep confidence scores and matching method for review.
- Never include a low-confidence match in a hidden adjustment; show it in the review queue.
- Buffer events locally when connectivity is unavailable and retry with the same `event_id`.
- Calibrate the line and camera angle per vehicle before the first live trip.
