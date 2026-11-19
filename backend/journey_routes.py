from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.journey_storage import save_journey
from backend.journeys import price_journey

router = APIRouter(prefix="/journeys", tags=["journeys"])


class JourneyRequest(BaseModel):
    boarding_event_id: str
    alighting_event_id: str
    boarding_stage: str
    alighting_stage: str


@router.get("/quote")
def quote_journey(
    boarding_event_id: str,
    alighting_event_id: str,
    boarding_stage: str,
    alighting_stage: str,
):
    try:
        return price_journey(
            boarding_event_id,
            alighting_event_id,
            boarding_stage,
            alighting_stage,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("", status_code=201)
def create_journey(request: JourneyRequest, response: Response):
    try:
        journey = save_journey(
            request.boarding_event_id,
            request.alighting_event_id,
            request.boarding_stage,
            request.alighting_stage,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if journey["status"] == "already_saved":
        response.status_code = 200

    return journey
