import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

from ..services.medication_times import parse_take_times

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats", response_model=schemas.DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    user_count = db.query(models.User).count()
    record_count = db.query(models.MedicalCase).count()
    medication_count = db.query(models.Medication).count()
    reminder_count = sum(len(parse_take_times(item)) for item in db.query(models.Medication).all())

    return {
        "userCount": user_count,
        "recordCount": record_count,
        "medicationCount": medication_count,
        "reminderCount": reminder_count,
    }


@router.get("/health-profile/{user_id}", response_model=schemas.HealthProfileInsight)
def get_health_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    medications = db.query(models.Medication).filter(models.Medication.user_id == user_id).all()
    chronic_names = [
        item.strip()
        for item in re.split(r"[、,，;；\n\s]+", user.chronic_diseases or "")
        if item.strip()
    ]
    joined = "、".join(chronic_names)
    suggestions = []
    if "高血压" in joined:
        suggestions.append("控制盐分摄入")
    if "糖尿病" in joined:
        suggestions.append("控制糖分摄入")
    if medications:
        suggestions.append("按时服药")

    chronic_count = len(chronic_names)
    if chronic_count >= 3:
        risk = "高风险"
    elif chronic_count == 2:
        risk = "中风险"
    else:
        risk = "低风险"

    if not suggestions:
        suggestions.append("保持规律作息，定期复查")

    return {
        "name": user.name,
        "age": user.age,
        "chronicCount": chronic_count,
        "medicationCount": len(medications),
        "risk": risk,
        "suggestions": suggestions,
    }
