from fastapi import APIRouter, HTTPException

from backend.fares import calculate_fare

router = APIRouter(prefix="/fares", tags=["fares"])


@router.get("/quote")
def quote_fare(boarding_stage: str, alighting_stage: str):
    try:
        fare_kes = calculate_fare(boarding_stage, alighting_stage)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return {
        "boarding_stage": boarding_stage,
        "alighting_stage": alighting_stage,
        "fare_kes": fare_kes,
    }
