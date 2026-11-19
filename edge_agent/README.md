# PSV-Radar edge agent

The edge agent runs beside the camera, not in the browser and not inside the
FastAPI process. A detector adapter calls `EventPublisher.publish()` whenever
its virtual door line is crossed. The included JSONL source is a safe MVP
replay path for testing backend-to-dashboard communication before attaching a
live camera model.

## Replay a crossing stream

For normal operation, provision the camera once and store its device credentials
as protected environment variables. The agent exchanges the device credential
for a trip session automatically; no session token needs to be copied per trip:

```bash
PSV_CAMERA_DEVICE_ID='cam-1' \
PSV_CAMERA_DEVICE_TOKEN='device-token-from-provisioning' \
python3 -m edge_agent.agent \
  --vehicle-id psv-starter-demo \
  --trip-id trip-001 \
  --route-id demo-route \
  --events edge_agent/sample_crossings.jsonl
```

The trip must already be active and the device must be assigned to the vehicle.
The long-lived device token is only shown once during provisioning and should be
stored in a device secret file or service manager, never committed to source.

For manual dashboard testing, a short-lived session token is still accepted:

From the repository root:

```bash
PSV_CAMERA_SESSION_TOKEN='session-token-from-POST-/operations/trips/{id}/camera-session' \
python3 -m edge_agent.agent \
  --vehicle-id psv-starter-demo \
  --trip-id trip-001 \
  --route-id demo-route \
  --events edge_agent/sample_crossings.jsonl
```

To inspect the payloads without sending them:

```bash
python3 -m edge_agent.agent --dry-run \
  --vehicle-id psv-starter-demo --trip-id trip-001 --route-id demo-route \
  --events edge_agent/sample_crossings.jsonl
```

The real camera adapter should emit one event per line crossing, use a stable
`event_id` for retries, keep `track_id` local to the camera view, and never
send video or face data to the backend.
