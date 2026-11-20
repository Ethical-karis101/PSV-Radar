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

## Browser webcam demo (recommended for the MVP presentation)

This runs a local, touch-friendly camera console in a browser. The local Python
service runs person detection and tracking; the browser only previews the camera
and displays boxes, the virtual door line, and crossing counts. Video frames stay
on this machine. Only crossing-event metadata and a device heartbeat are sent to
the backend. Bind the service to `127.0.0.1` so the local camera console is not
exposed to the network.

Install the optional dependencies (the first model run downloads `yolo11n.pt`):

```bash
python3 -m pip install -r edge_agent/requirements-webcam.txt
```

Start the backend, provision a camera device for the vehicle, and have the
conductor create/start a trip. Then run this from the repository root, replacing
the device credentials with the values returned at provisioning:

```bash
PSV_RADAR_API_URL='http://localhost:8000' \
PSV_RADAR_DASHBOARD_URL='http://localhost:5173' \
PSV_CAMERA_DEVICE_ID='cam-1' \
PSV_CAMERA_DEVICE_TOKEN='device-token-from-provisioning' \
python3 -m uvicorn edge_agent.webcam_ui:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765> on the camera computer, allow camera access, and
press **Start camera demo**. Adjust the door line so it crosses the visible
threshold, and choose which direction means boarding. The console follows the
active trip and the conductor-selected route stage automatically. The owner can
watch the camera heartbeat and event totals in **Dashboard → Cameras**.

The browser console is a controlled hackathon demonstration, not a production
Android camera app: keep the computer attended, use consenting participants,
and verify the camera angle and crossing direction before presenting. It does
not record video, guarantee passenger identity across a trip, or maintain an
offline event queue. The one-time device token must be kept private.

## Laptop webcam CLI prototype

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
