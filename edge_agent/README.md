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

feat/yolo-edge-detector
## Live detection with YOLO

`edge_agent/yolo_detector.py` tracks people with Ultralytics YOLO and publishes
one event each time a tracked person crosses a virtual line. Install the
detector dependencies on the camera device (not needed on the server):

```bash
pip install -r edge_agent/requirements.txt
```

Then run it from the repository root. `--source` is a camera index, an RTSP URL,
or a video file. Start with `--dry-run` to print events without sending them:

```bash
python3 -m edge_agent.yolo_detector --dry-run \
  --source 0 --stage-id stage-a \
  --vehicle-id psv-starter-demo --trip-id trip-001 --route-id demo-route
```

For production, drop `--dry-run`, set `PSV_RADAR_API_URL` and the device
credentials as described above.

- The line is horizontal at the middle of the frame by default. Change it with
  `--orientation vertical|horizontal` and `--line 0.0-1.0`.
- By default, moving down (or right) counts as boarding and the opposite as
  alighting. Use `--invert` if your camera faces the other way.
- `--stage-id` is fixed for the run; restart at each stage until the agent reads
  the stage from the trip.
- Event ids are derived from trip, track and crossing number, so retries do not
  double-count. Only crossing events are sent: no video, frames or faces.

=======
## Laptop webcam prototype

This optional prototype runs Ultralytics person detection and BoT-SORT tracking
against a local webcam, then publishes virtual-line crossings through the same
event publisher and device APIs. It is for controlled testing with consenting
participants, not unattended vehicle use. It does not record or upload video.

Install the optional dependencies (prefer a virtual environment):

```bash
python3 -m pip install -r edge_agent/requirements-webcam.txt
```

The first run downloads the pretrained `yolo11n.pt` model. Start the backend,
configure/provision a camera device and route, then start and stage an active
trip from the conductor dashboard. On the laptop:

```bash
PSV_RADAR_API_URL='http://localhost:8000' \
PSV_CAMERA_DEVICE_ID='cam-1' \
PSV_CAMERA_DEVICE_TOKEN='device-token-from-provisioning' \
python3 -m edge_agent.webcam --camera 0 \
  --line 0.5,0.1,0.5,0.9 --boarding-direction positive
```

The line uses normalized frame coordinates (`x1,y1,x2,y2`); tune it to the
visible door threshold. A crossing from the negative side to the positive side
is boarding by default. Set `--boarding-direction negative` if the camera view
is reversed. Press `q` to stop. If the laptop webcam is not index 0, try
`--camera 1`.

To test detection and crossing payloads without a backend or device credential:

```bash
python3 -m edge_agent.webcam --dry-run \
  --vehicle-id demo-vehicle --trip-id demo-trip --route-id demo-route \
  --stage-id stage-a --line 0.5,0.1,0.5,0.9
```

The prototype polls the device's active-trip context and uses the conductor's
latest stage when publishing. It skips events if no active trip or stage is
available. Network retries are limited to immediate retry behavior; there is
no persistent offline queue yet. A local tracker ID is only a short-lived
camera-view ID, not a guaranteed identity from boarding to alighting. Verify
crossing direction and false detections using test clips before interpreting
counts as operational figures.
main
