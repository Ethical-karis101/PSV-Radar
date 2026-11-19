from fastapi import FastAPI
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

app = FastAPI(title="PSV-Radar")


@app.get("/health")
def health():
    return {"status": "ok"}

class PassengerEvent(BaseModel):
    event_id: str
    vehicle_id: str
    event_type: Literal["boarding", "alighting"]
    occurred_at: datetime
    
@app.post("/events/validate")
def validate_event(event: PassengerEvent):
    return {"valid": True, "event_id": event.event_id}
