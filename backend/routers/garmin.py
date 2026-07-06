import logging

from fastapi import APIRouter, HTTPException

from ..services import garmin_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/garmin", tags=["garmin"])


@router.get("/status")
def garmin_status():
    return garmin_service.get_status()


@router.get("/overview")
def garmin_overview(date: str | None = None, refresh: bool = False):
    try:
        return garmin_service.get_overview(date, force=refresh)
    except garmin_service.GarminNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except garmin_service.GarminAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/history")
def garmin_history(days: int = 7):
    return garmin_service.get_history(days)
