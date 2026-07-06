from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services.medication_times import apply_take_times_to_medication, parse_take_times, to_medication_schema

router = APIRouter(prefix="/medications", tags=["medications"])


@router.get("", response_model=list[schemas.Medication])
def list_medications(user_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    query = db.query(models.Medication)
    if user_id is not None:
        query = query.filter(models.Medication.user_id == user_id)
    medications = query.order_by(models.Medication.id.desc()).all()
    medications.sort(key=lambda item: (parse_take_times(item)[0] if parse_take_times(item) else "99:99", item.id))
    return [to_medication_schema(item) for item in medications]


@router.post("", response_model=schemas.Medication, status_code=status.HTTP_201_CREATED)
def create_medication(medication: schemas.MedicationCreate, db: Session = Depends(get_db)):
    if not db.get(models.User, medication.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    payload = medication.model_dump(exclude={"take_times", "take_time"})
    db_medication = models.Medication(**payload)
    apply_take_times_to_medication(db_medication, medication.take_times, medication.take_time)
    db.add(db_medication)
    db.commit()
    db.refresh(db_medication)
    return to_medication_schema(db_medication)


@router.put("/{medication_id}", response_model=schemas.Medication)
def update_medication(medication_id: int, medication: schemas.MedicationUpdate, db: Session = Depends(get_db)):
    db_medication = db.get(models.Medication, medication_id)
    if not db_medication:
        raise HTTPException(status_code=404, detail="Medication not found")
    if not db.get(models.User, medication.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    payload = medication.model_dump(exclude={"take_times", "take_time"})
    for key, value in payload.items():
        setattr(db_medication, key, value)
    apply_take_times_to_medication(db_medication, medication.take_times, medication.take_time)
    db.commit()
    db.refresh(db_medication)
    return to_medication_schema(db_medication)


@router.delete("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_medication(medication_id: int, db: Session = Depends(get_db)):
    db_medication = db.get(models.Medication, medication_id)
    if not db_medication:
        raise HTTPException(status_code=404, detail="Medication not found")

    db.delete(db_medication)
    db.commit()
    return None
