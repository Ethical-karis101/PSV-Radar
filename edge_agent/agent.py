"""Publish camera-crossing events to PSV-Radar.

The detector is intentionally a separate adapter. This module can replay
crossings for the MVP and provides the stable publisher that a real camera
adapter calls after line crossing.
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class Crossing:
    event_type: str
    stage_id: str
    track_id: str
    confidence: float
    occurred_at: str
    door_id: str


class EventPublisher:
    def __init__(self, api_url: str, session_token: str | None, vehicle_id: str,
                 trip_id: str, route_id: str, device_id: str | None = None,
                 device_token: str | None = None, dry_run: bool = False):
        self.api_url = api_url.rstrip('/')
        self.endpoint = f"{self.api_url}/events"
        self.session_token = session_token
        self.vehicle_id = vehicle_id
        self.trip_id = trip_id
        self.route_id = route_id
        self.device_id = device_id
        self.device_token = device_token
        self.dry_run = dry_run

    def _authenticate_device(self):
        request = urllib.request.Request(
            f"{self.api_url}/device/session",
            data=json.dumps({
                "device_id": self.device_id,
                "device_token": self.device_token,
                "trip_id": self.trip_id,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace").strip()
            raise RuntimeError(
                f"Device authentication failed with HTTP {error.code}: {detail or error.reason}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Could not authenticate camera device: {error}") from error
        self.session_token = payload["session_token"]

    def _ensure_session(self):
        if not self.session_token and self.device_id and self.device_token:
            self._authenticate_device()

    def publish(self, crossing: Crossing, event_id: str | None = None):
        if crossing.event_type not in ("boarding", "alighting"):
            raise ValueError("event_type must be boarding or alighting")
        payload = {
            "event_id": event_id or str(uuid4()),
            "vehicle_id": self.vehicle_id,
            "trip_id": self.trip_id,
            "route_id": self.route_id,
            "stage_id": crossing.stage_id,
            "event_type": crossing.event_type,
            "occurred_at": crossing.occurred_at,
            "track_id": crossing.track_id,
            "door_id": crossing.door_id,
            "source": "camera",
            "confidence": max(0.0, min(1.0, crossing.confidence)),
        }
        if self.dry_run:
            print(json.dumps(payload))
            return
        self._ensure_session()
        last_error = None
        refreshed = False
        for attempt in range(3):
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.session_token}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    if response.status not in (200, 201):
                        raise RuntimeError(f"Radar returned HTTP {response.status}")
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors="replace").strip()
                if error.code == 401 and not refreshed and self.device_id and self.device_token:
                    self.session_token = None
                    self._authenticate_device()
                    refreshed = True
                    continue
                raise RuntimeError(
                    f"Radar rejected event with HTTP {error.code}: {detail or error.reason}"
                ) from error
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Could not publish event {payload['event_id']}: {last_error}")


def load_crossings(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            try:
                value = json.loads(raw_line)
                yield value.get("event_id"), Crossing(
                    event_type=value["event_type"], stage_id=value["stage_id"],
                    track_id=value.get("track_id", f"replay-{line_number}"),
                    confidence=float(value.get("confidence", 0.65)),
                    occurred_at=value.get("occurred_at", datetime.now(timezone.utc).isoformat()),
                    door_id=value.get("door_id", "main-door"),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid crossing on line {line_number}: {error}") from error


def main():
    parser = argparse.ArgumentParser(description="Publish PSV-Radar camera events")
    parser.add_argument("--api-url", default=os.getenv("PSV_RADAR_API_URL", "http://localhost:8000"))
    parser.add_argument("--session-token", default=os.getenv("PSV_CAMERA_SESSION_TOKEN"))
    parser.add_argument("--device-id", default=os.getenv("PSV_CAMERA_DEVICE_ID"))
    parser.add_argument("--device-token", default=os.getenv("PSV_CAMERA_DEVICE_TOKEN"))
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--events", type=Path, required=True, help="JSONL crossings from the detector adapter")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    has_manual_session = bool(args.session_token)
    has_device_credentials = bool(args.device_id and args.device_token)
    if not args.dry_run and not has_manual_session and not has_device_credentials:
        parser.error("provide --session-token, or both --device-id and --device-token")
    publisher = EventPublisher(args.api_url, args.session_token, args.vehicle_id,
                               args.trip_id, args.route_id, args.device_id,
                               args.device_token, args.dry_run)
    for event_id, crossing in load_crossings(args.events):
        result = publisher.publish(crossing, event_id)
        if result is not None:
            print(f"published {crossing.event_type} event {result['event_id']}")


if __name__ == "__main__":
    main()
