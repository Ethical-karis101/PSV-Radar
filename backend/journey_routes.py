from fastapi import APIRouter, HTTPException

from backend.journeys import price_journey

router = APIRouter(prefix="/journeys", tags=["journeys"])


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
