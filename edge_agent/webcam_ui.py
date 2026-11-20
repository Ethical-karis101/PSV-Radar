"""Local browser UI and inference API for a controlled PSV-Radar webcam demo."""

import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from edge_agent.agent import Crossing, EventPublisher
from edge_agent.webcam import active_trip, line_side


API_URL = os.getenv("PSV_RADAR_API_URL", "http://localhost:8000")
DEVICE_ID = os.getenv("PSV_CAMERA_DEVICE_ID", "")
DEVICE_TOKEN = os.getenv("PSV_CAMERA_DEVICE_TOKEN", "")
MODEL_PATH = os.getenv("PSV_CAMERA_MODEL", "yolo11n.pt")
DASHBOARD_URL = os.getenv("PSV_RADAR_DASHBOARD_URL", "http://localhost:5173")
MAX_FRAME_BYTES = 2_000_000
# When set (always set it on a public deployment), every route except /health
# requires HTTP Basic auth with this password and any username.
UI_PASSWORD = os.getenv("CAMERA_UI_PASSWORD", "")


class CameraConfig(BaseModel):
    line_x: float = Field(ge=0.05, le=0.95)
    boarding_direction: str = Field(pattern="^(positive|negative)$")


class WebcamRuntime:
    def __init__(self):
        self.lock = Lock()
        self.model = None
        self.running = False
        self.error = ""
        self.line_x = 0.5
        self.boarding_direction = "positive"
        self.trip = None
        self.publisher = None
        self.previous_sides = {}
        self.last_crossings = {}
        self.boardings = 0
        self.alightings = 0
        self.recent_events = []
        self.last_inference_ms = 0
        self.session_id = ""
        self.next_refresh = 0.0
        self.next_heartbeat = 0.0

    def start(self):
        if not DEVICE_ID or not DEVICE_TOKEN:
            raise RuntimeError("Set PSV_CAMERA_DEVICE_ID and PSV_CAMERA_DEVICE_TOKEN before starting the demo.")
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError("Install optional webcam dependencies with: python3 -m pip install -r edge_agent/requirements-webcam.txt") from error
        with self.lock:
            if self.model is None:
                self.model = YOLO(MODEL_PATH)
            self.running = True
            self.error = ""
            self.previous_sides.clear()
            self.last_crossings.clear()
            self.boardings = 0
            self.alightings = 0
            self.recent_events.clear()
            self.session_id = secrets.token_hex(4)
            self.next_refresh = 0
            self.next_heartbeat = 0
        return self.status()

    def stop(self):
        with self.lock:
            self.running = False
            self.trip = None
            self.publisher = None
        return self.status()

    def set_config(self, config):
        with self.lock:
            self.line_x = config.line_x
            self.boarding_direction = config.boarding_direction
        return self.status()

    def _post_json(self, path, payload):
        request = urllib.request.Request(
            f"{API_URL.rstrip('/')}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.loads(response.read())

    def _refresh_context(self, current_time):
        try:
            latest = active_trip(API_URL, DEVICE_ID, DEVICE_TOKEN)
            trip = latest.get("trip") if latest.get("state") == "active_trip" else None
            if trip:
                trip["vehicle_id"] = latest["vehicle_id"]
                trip["door_id"] = latest["door_id"]
            with self.lock:
                previous_id = self.trip.get("trip_id") if self.trip else None
                self.trip = trip
                if trip and trip["trip_id"] != previous_id:
                    self.publisher = EventPublisher(
                        API_URL, None, trip["vehicle_id"], trip["trip_id"],
                        trip["route_id"], DEVICE_ID, DEVICE_TOKEN,
                    )
                elif not trip:
                    self.publisher = None
                self.error = ""
            self.next_refresh = current_time + 2
        except RuntimeError as error:
            with self.lock:
                self.error = str(error)
            self.next_refresh = current_time + 5

    def _heartbeat(self, current_time):
        try:
            self._post_json("/device/heartbeat", {"device_id": DEVICE_ID, "device_token": DEVICE_TOKEN})
            self.next_heartbeat = current_time + 10
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
            with self.lock:
                self.error = f"Camera heartbeat unavailable: {error}"
            self.next_heartbeat = current_time + 10

    def process_frame(self, encoded_frame):
        import cv2
        import numpy as np

        current_time = time.monotonic()
        if not self.running or self.model is None:
            raise RuntimeError("Start the camera before sending frames.")
        if current_time >= self.next_refresh:
            self._refresh_context(current_time)
        if current_time >= self.next_heartbeat:
            self._heartbeat(current_time)

        frame = cv2.imdecode(np.frombuffer(encoded_frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode camera frame.")
        height, width = frame.shape[:2]
        started = time.perf_counter()
        result = self.model.track(frame, persist=True, tracker="botsort.yaml", classes=[0], conf=0.4, verbose=False)[0]
        self.last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
        boxes = result.boxes
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else []
        xyxy = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        detections = []
        crossings = []
        with self.lock:
            line = (self.line_x, 0.0, self.line_x, 1.0)
            trip = dict(self.trip) if self.trip else None
            publisher = self.publisher
            direction = self.boarding_direction
            for index, track_id in enumerate(ids):
                left, top, right, bottom = xyxy[index]
                cx, cy = (left + right) / (2 * width), (top + bottom) / (2 * height)
                detections.append({"track_id": int(track_id), "x": left / width, "y": top / height,
                                   "w": (right - left) / width, "h": (bottom - top) / height,
                                   "confidence": round(float(confidences[index]), 3)})
                side = line_side(cx, cy, line)
                previous = self.previous_sides.get(track_id)
                self.previous_sides[track_id] = side
                if not previous or not side or previous == side or current_time - self.last_crossings.get(track_id, 0) < 1.5:
                    continue
                entered_positive = previous < 0 < side
                is_boarding = entered_positive == (direction == "positive")
                event_type = "boarding" if is_boarding else "alighting"
                event = {"event_type": event_type, "track_id": int(track_id), "confidence": float(confidences[index]), "published": False}
                if trip and trip.get("current_stage_id") and publisher:
                    crossing = Crossing(
                        event_type, trip["current_stage_id"], f"webcam-{self.session_id}-{track_id}",
                        float(confidences[index]), datetime.now(timezone.utc).isoformat(), trip["door_id"],
                    )
                    try:
                        publisher.publish(crossing)
                        event["published"] = True
                        event["stage_name"] = trip.get("current_stage_name")
                        event["trip_id"] = trip["trip_id"]
                        self.error = ""
                    except RuntimeError as error:
                        self.error = str(error)
                if event_type == "boarding":
                    self.boardings += 1
                else:
                    self.alightings += 1
                self.recent_events.insert(0, event)
                del self.recent_events[12:]
                crossings.append(event)
                self.last_crossings[track_id] = current_time
            response = {
                "detections": detections, "crossings": crossings,
                "boardings": self.boardings, "alightings": self.alightings,
                "inference_ms": self.last_inference_ms,
                "trip": {key: trip.get(key) for key in ("trip_id", "route_name", "current_stage_name") if trip and trip.get(key)},
                "error": self.error,
            }
        return response

    def status(self):
        with self.lock:
            return {
                "running": self.running, "device_id": DEVICE_ID or None,
                "dashboard_url": DASHBOARD_URL,
                "configured": bool(DEVICE_ID and DEVICE_TOKEN), "trip": self.trip,
                "line_x": self.line_x, "boarding_direction": self.boarding_direction,
                "boardings": self.boardings, "alightings": self.alightings,
                "recent_events": list(self.recent_events), "inference_ms": self.last_inference_ms,
                "error": self.error,
            }


runtime = WebcamRuntime()
app = FastAPI(title="PSV-Radar local webcam demo")


@app.middleware("http")
async def require_password(request: Request, call_next):
    if not UI_PASSWORD or request.url.path == "/health":
        return await call_next(request)
    supplied = ""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            supplied = base64.b64decode(header[6:]).decode().partition(":")[2]
        except ValueError:
            supplied = ""
    if not secrets.compare_digest(supplied.encode(), UI_PASSWORD.encode()):
        return JSONResponse({"detail": "Authentication required."}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="PSV-Radar camera"'})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def camera_page():
    page = Path(__file__).with_name("webcam_ui.html").read_text(encoding="utf-8")
    return HTMLResponse(page)


@app.get("/api/status")
def camera_status():
    return runtime.status()


@app.post("/api/start")
def start_camera():
    try:
        return runtime.start()
    except (RuntimeError, OSError) as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/stop")
def stop_camera():
    return runtime.stop()


@app.post("/api/config")
def configure_camera(config: CameraConfig):
    return runtime.set_config(config)


@app.post("/api/frame")
async def analyze_frame(request: Request):
    frame = await request.body()
    if not frame or len(frame) > MAX_FRAME_BYTES:
        raise HTTPException(413, "Camera frame must be between 1 byte and 2 MB.")
    try:
        return await run_in_threadpool(runtime.process_frame, frame)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(409, str(error)) from error


@app.on_event("shutdown")
def stop_on_shutdown():
    runtime.stop()
