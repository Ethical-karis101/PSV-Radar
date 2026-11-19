from backend.database import save_event
from backend.journey_storage import save_journey
from backend.revenue_routes import initialize_revenue_storage

DEMO_VEHICLE = "psv-starter-demo"
DEMO_DAY = "2026-11-19"


def seed_demo():
    initialize_revenue_storage()

    events = (
        ("starter-demo-board-001", "boarding", f"{DEMO_DAY}T08:30:00+03:00"),
        ("starter-demo-alight-001", "alighting", f"{DEMO_DAY}T08:45:00+03:00"),
    )

    for event_id, event_type, occurred_at in events:
        result = save_event(event_id, DEMO_VEHICLE, event_type, occurred_at)
        if result == "conflict":
            raise SystemExit(f"Demo event ID already belongs to different data: {event_id}")

    journey = save_journey(
        "starter-demo-board-001",
        "starter-demo-alight-001",
        "stage-a",
        "stage-c",
    )

    print(f"Demo journey status: {journey['status']}")
    print(f"Vehicle: {DEMO_VEHICLE} | Date: {DEMO_DAY}")
    print(f"Expected revenue: KSh {journey['fare_kes']}")


if __name__ == "__main__":
    seed_demo()
