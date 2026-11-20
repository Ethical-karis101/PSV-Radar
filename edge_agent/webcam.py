"""Laptop-webcam person detection and virtual-door crossing prototype."""

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from edge_agent.agent import Crossing, EventPublisher


def parse_line(value):
    try:
        points = [float(part.strip()) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("line must be x1,y1,x2,y2 using normalized 0..1 coordinates") from error
    if len(points) != 4 or any(point < 0 or point > 1 for point in points):
        raise argparse.ArgumentTypeError("line must be x1,y1,x2,y2 using normalized 0..1 coordinates")
    if points[0] == points[2] and points[1] == points[3]:
        raise argparse.ArgumentTypeError("line endpoints must be different")
    return tuple(points)


def line_side(point_x, point_y, line):
    """Return the signed side of a point relative to a normalized line."""
    x1, y1, x2, y2 = line
    cross = (y2 - y1) * (point_x - x1) - (x2 - x1) * (point_y - y1)
    return 1 if cross > 0 else (-1 if cross < 0 else 0)


def active_trip(api_url, device_id, device_token):
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/device/active-trip",
        data=json.dumps({"device_id": device_id, "device_token": device_token}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace").strip()
        raise RuntimeError(f"Radar returned HTTP {error.code}: {detail or error.reason}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not reach Radar: {error}") from error


def main():
    parser = argparse.ArgumentParser(
        description="Prototype person detection and virtual-door crossing from a laptop webcam"
    )
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics person-detection model")
    parser.add_argument("--line", type=parse_line, default=parse_line("0.5,0.1,0.5,0.9"),
                        help="virtual door line as normalized x1,y1,x2,y2 (default: vertical center)")
    parser.add_argument("--boarding-direction", choices=("positive", "negative"), default="positive",
                        help="which signed line crossing means boarding; calibrate for camera view")
    parser.add_argument("--confidence", type=float, default=0.45, help="minimum person detection confidence")
    parser.add_argument("--tracker", default="botsort.yaml", help="Ultralytics tracker configuration")
    parser.add_argument("--api-url", default=os.getenv("PSV_RADAR_API_URL", "http://localhost:8000"))
    parser.add_argument("--device-id", default=os.getenv("PSV_CAMERA_DEVICE_ID"))
    parser.add_argument("--device-token", default=os.getenv("PSV_CAMERA_DEVICE_TOKEN"))
    parser.add_argument("--dry-run", action="store_true", help="print events instead of sending them")
    parser.add_argument("--stage-id", help="required with --dry-run; no backend trip lookup is made")
    parser.add_argument("--vehicle-id", help="required with --dry-run")
    parser.add_argument("--trip-id", help="required with --dry-run")
    parser.add_argument("--route-id", help="required with --dry-run")
    parser.add_argument("--door-id", default="main-door", help="door ID for --dry-run events")
    args = parser.parse_args()

    if not 0 <= args.confidence <= 1:
        parser.error("--confidence must be between 0 and 1")
    if args.dry_run:
        if not all((args.stage_id, args.vehicle_id, args.trip_id, args.route_id)):
            parser.error("--dry-run requires --stage-id, --vehicle-id, --trip-id, and --route-id")
    elif not args.device_id or not args.device_token:
        parser.error("set PSV_CAMERA_DEVICE_ID and PSV_CAMERA_DEVICE_TOKEN for live publishing")

    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as error:
        raise SystemExit(
            "Webcam dependencies are missing. Install them with: "
            "python3 -m pip install -r edge_agent/requirements-webcam.txt"
        ) from error

    model = YOLO(args.model)
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise SystemExit(f"Could not open webcam index {args.camera}; try --camera 1")

    previous_sides = {}
    last_crossings = {}
    publisher = None
    trip_context = None
    next_context_refresh = 0.0
    print("Webcam prototype running. Press q to quit. Do not point it at passengers without their consent.")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Camera frame unavailable; stopping.")
                break
            height, width = frame.shape[:2]
            x1, y1, x2, y2 = args.line
            pixel_line = (int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height))
            cv2.line(frame, pixel_line[:2], pixel_line[2:], (70, 220, 255), 2)

            now_monotonic = cv2.getTickCount() / cv2.getTickFrequency()
            if not args.dry_run and now_monotonic >= next_context_refresh:
                try:
                    latest = active_trip(args.api_url, args.device_id, args.device_token)
                    trip_context = latest.get("trip") if latest.get("state") == "active_trip" else None
                    if trip_context:
                        trip_context["vehicle_id"] = latest["vehicle_id"]
                        trip_context["door_id"] = latest["door_id"]
                    if trip_context and (publisher is None or publisher.trip_id != trip_context["trip_id"]):
                        publisher = EventPublisher(
                            args.api_url, None, latest["vehicle_id"], trip_context["trip_id"],
                            trip_context["route_id"], args.device_id, args.device_token,
                        )
                    next_context_refresh = now_monotonic + 2
                except RuntimeError as error:
                    trip_context = None
                    print(f"Context unavailable; crossings will not be sent: {error}")
                    next_context_refresh = now_monotonic + 5

            results = model.track(
                frame, persist=True, tracker=args.tracker, classes=[0],
                conf=args.confidence, verbose=False,
            )
            result = results[0]
            boxes = result.boxes
            ids = boxes.id.int().cpu().tolist() if boxes.id is not None else []
            xywh = boxes.xywh.cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            for index, track_id in enumerate(ids):
                center_x = xywh[index][0] / width
                center_y = xywh[index][1] / height
                side = line_side(center_x, center_y, args.line)
                previous = previous_sides.get(track_id)
                previous_sides[track_id] = side
                if not previous or not side or previous == side:
                    continue
                if now_monotonic - last_crossings.get(track_id, 0) < 1.5:
                    continue
                entered_positive = previous < 0 < side
                is_boarding = entered_positive == (args.boarding_direction == "positive")
                event_type = "boarding" if is_boarding else "alighting"
                stage_id = args.stage_id if args.dry_run else (trip_context or {}).get("current_stage_id")
                if not stage_id:
                    print(f"Detected {event_type} crossing for track {track_id}, but no active trip/stage is available")
                    continue
                context = {
                    "vehicle_id": args.vehicle_id if args.dry_run else (trip_context or {}).get("vehicle_id"),
                    "trip_id": args.trip_id if args.dry_run else (trip_context or {}).get("trip_id"),
                    "route_id": args.route_id if args.dry_run else (trip_context or {}).get("route_id"),
                    "door_id": args.door_id if args.dry_run else (trip_context or {}).get("door_id"),
                }
                if publisher is None and not args.dry_run:
                    continue
                crossing = Crossing(
                    event_type, stage_id, f"webcam-{track_id}", float(confidences[index]),
                    datetime.now(timezone.utc).isoformat(), context["door_id"],
                )
                try:
                    if args.dry_run:
                        EventPublisher(args.api_url, None, context["vehicle_id"], context["trip_id"],
                                       context["route_id"], dry_run=True).publish(crossing)
                    else:
                        publisher.publish(crossing)
                    last_crossings[track_id] = now_monotonic
                    print(f"{event_type}: track {track_id} at stage {stage_id}")
                except RuntimeError as error:
                    print(f"Could not publish crossing: {error}")

            frame = result.plot(img=frame)
            state = "DRY RUN" if args.dry_run else ("ACTIVE TRIP" if trip_context else "WAITING FOR ACTIVE TRIP")
            cv2.putText(frame, state, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                        (40, 210, 80) if trip_context or args.dry_run else (0, 165, 255), 2)
            cv2.imshow("PSV-Radar webcam prototype · press q to quit", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
