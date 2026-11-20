"""YOLO door-line detector for the PSV-Radar edge agent.

Tracks people with Ultralytics YOLO, and when a tracked person crosses a
virtual line, publishes one boarding or alighting event through EventPublisher.
Only integer crossing events leave the device: no frames, video or faces.

Run from the repository root (see edge_agent/README.md):

    python3 -m edge_agent.yolo_detector --source 0 --stage-id stage-a \
        --vehicle-id V --trip-id T --route-id R --dry-run
"""

import argparse
import hashlib
import os
from datetime import datetime, timezone

from edge_agent.agent import Crossing, EventPublisher


class LineCounter:
    """Detects when tracked points cross a line, per track id.

    The line is vertical (x = position * width) or horizontal
    (y = position * height). Moving from the low side to the high side counts
    as `positive_event`; the opposite direction is the other event type.
    A track must be seen on both sides, so a person standing on the line or
    jittering across it by a pixel is not counted: `margin` is a dead zone
    (fraction of the frame) the point must leave before the side flips.
    """

    def __init__(self, orientation="vertical", position=0.5, margin=0.02,
                 positive_event="boarding"):
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("orientation must be vertical or horizontal")
        self.orientation = orientation
        self.position = position
        self.margin = margin
        self.positive_event = positive_event
        self.negative_event = "alighting" if positive_event == "boarding" else "boarding"
        self._side = {}      # track_id -> -1 or +1, last confirmed side
        self._counts = {}    # track_id -> crossings so far (for stable event ids)

    def update(self, track_id, x, y, width, height):
        """Return (event_type, crossing_index) when this update crosses, else None."""
        value, size = (x, width) if self.orientation == "vertical" else (y, height)
        offset = value / size - self.position
        if abs(offset) < self.margin:
            return None
        side = 1 if offset > 0 else -1
        previous = self._side.get(track_id)
        self._side[track_id] = side
        if previous is None or previous == side:
            return None
        index = self._counts.get(track_id, 0) + 1
        self._counts[track_id] = index
        return (self.positive_event if side > 0 else self.negative_event), index

    def forget(self, active_ids):
        for track_id in set(self._side) - set(active_ids):
            self._side.pop(track_id, None)


def stable_event_id(trip_id, vehicle_id, track_id, index, event_type):
    """Same crossing always hashes to the same id, so retries never double-count."""
    raw = f"{trip_id}|{vehicle_id}|{track_id}|{index}|{event_type}"
    return "camera-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def run(args, publisher):
    try:
        import cv2  # noqa: F401
        from ultralytics import YOLO
    except ImportError as error:
        raise SystemExit(
            "Install detector dependencies first: pip install -r edge_agent/requirements.txt"
        ) from error

    source = int(args.source) if args.source.isdigit() else args.source
    model = YOLO(args.model)
    counter = LineCounter(args.orientation, args.line, args.margin,
                          "alighting" if args.invert else "boarding")
    # classes=[0] is "person" in COCO. persist keeps track ids between frames.
    stream = model.track(source=source, stream=True, persist=True, classes=[0],
                         conf=args.conf, verbose=False)
    for result in stream:
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            counter.forget([])
            continue
        height, width = result.orig_shape
        ids = boxes.id.int().tolist()
        confidences = boxes.conf.tolist()
        for track_id, box, confidence in zip(ids, boxes.xyxy.tolist(), confidences):
            x1, y1, x2, y2 = box
            # Bottom-centre of the box approximates where the person stands.
            hit = counter.update(track_id, (x1 + x2) / 2, y2, width, height)
            if hit is None:
                continue
            event_type, index = hit
            crossing = Crossing(
                event_type=event_type, stage_id=args.stage_id,
                track_id=f"track-{track_id}", confidence=float(confidence),
                occurred_at=datetime.now(timezone.utc).isoformat(), door_id=args.door_id,
            )
            event_id = stable_event_id(args.trip_id, args.vehicle_id, track_id, index, event_type)
            try:
                result_payload = publisher.publish(crossing, event_id)
            except RuntimeError as error:
                print(f"publish failed: {error}")
                continue
            if result_payload is not None:
                print(f"published {event_type} event {event_id}")
        counter.forget(ids)


def main():
    parser = argparse.ArgumentParser(description="PSV-Radar YOLO door-line detector")
    parser.add_argument("--api-url", default=os.getenv("PSV_RADAR_API_URL", "http://localhost:8000"))
    parser.add_argument("--session-token", default=os.getenv("PSV_CAMERA_SESSION_TOKEN"))
    parser.add_argument("--device-id", default=os.getenv("PSV_CAMERA_DEVICE_ID"))
    parser.add_argument("--device-token", default=os.getenv("PSV_CAMERA_DEVICE_TOKEN"))
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--stage-id", required=True, help="Current stage; fixed for this run")
    parser.add_argument("--door-id", default="main-door")
    parser.add_argument("--source", default="0", help="Camera index, RTSP URL or video file")
    parser.add_argument("--model", default="yolov8n.pt", help="Ultralytics weights (downloaded on first run)")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--orientation", choices=["vertical", "horizontal"], default="horizontal")
    parser.add_argument("--line", type=float, default=0.5, help="Line position as a fraction of the frame")
    parser.add_argument("--margin", type=float, default=0.02)
    parser.add_argument("--invert", action="store_true",
                        help="Treat movement toward the low side (up/left) as boarding instead of alighting")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.session_token and not (args.device_id and args.device_token):
        parser.error("provide --session-token, or both --device-id and --device-token")
    publisher = EventPublisher(args.api_url, args.session_token, args.vehicle_id,
                               args.trip_id, args.route_id, args.device_id,
                               args.device_token, args.dry_run)
    run(args, publisher)


if __name__ == "__main__":
    main()
