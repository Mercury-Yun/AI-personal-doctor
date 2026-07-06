from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import case_service, case_summary_service
from ..services.attachment_service import resolve_path, save_upload

router = APIRouter(prefix="/medical_cases", tags=["medical_cases"])


def _get_case_or_404(db: Session, case_id: int) -> models.MedicalCase:
    case = db.get(models.MedicalCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


# ---------------------------------------------------------------------------
# 病例
# ---------------------------------------------------------------------------


@router.get("", response_model=list[schemas.MedicalCaseListItem])
def list_cases(
    user_id: int = Query(...),
    q: str | None = Query(default=None),
    visit_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(models.MedicalCase).filter(models.MedicalCase.user_id == user_id)
    if visit_type:
        query = query.filter(models.MedicalCase.visit_type == visit_type)
    if date_from:
        query = query.filter(models.MedicalCase.visit_date >= date_from)
    if date_to:
        query = query.filter(models.MedicalCase.visit_date <= date_to)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.MedicalCase.chief_complaint.like(like),
                models.MedicalCase.diagnosis.like(like),
                models.MedicalCase.hospital.like(like),
                models.MedicalCase.department.like(like),
                models.MedicalCase.doctor.like(like),
            )
        )
    return (
        query.order_by(models.MedicalCase.visit_date.desc(), models.MedicalCase.id.desc())
        .all()
    )


@router.get("/stats", response_model=schemas.CaseStats)
def get_case_stats(user_id: int = Query(...), db: Session = Depends(get_db)):
    return case_service.compute_case_stats(db, user_id)


@router.get("/{case_id}", response_model=schemas.MedicalCaseDetail)
def get_case(case_id: int, db: Session = Depends(get_db)):
    return case_service.to_case_detail(_get_case_or_404(db, case_id))


@router.post("", response_model=schemas.MedicalCaseDetail, status_code=status.HTTP_201_CREATED)
def create_case(payload: schemas.MedicalCaseCreate, db: Session = Depends(get_db)):
    if not db.get(models.User, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    case = models.MedicalCase(**payload.model_dump())
    db.add(case)
    db.commit()
    db.refresh(case)
    return case_service.to_case_detail(case)


@router.put("/{case_id}", response_model=schemas.MedicalCaseDetail)
def update_case(case_id: int, payload: schemas.MedicalCaseUpdate, db: Session = Depends(get_db)):
    case = _get_case_or_404(db, case_id)
    for key, value in payload.model_dump().items():
        setattr(case, key, value)
    db.commit()
    db.refresh(case)
    return case_service.to_case_detail(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: int, db: Session = Depends(get_db)):
    case_service.delete_case(db, _get_case_or_404(db, case_id))
    return None


@router.post("/{case_id}/summary", response_model=schemas.CaseSummary)
def summarize_case(case_id: int, db: Session = Depends(get_db)):
    """AI 实时总结单个病例，返回 8 键结构化摘要（不落库）。"""
    return case_summary_service.summarize_case(db, case_id)


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/examinations",
    response_model=schemas.MedicalExamination,
    status_code=status.HTTP_201_CREATED,
)
def create_examination(
    case_id: int, payload: schemas.MedicalExaminationCreate, db: Session = Depends(get_db)
):
    _get_case_or_404(db, case_id)
    exam = models.MedicalExamination(case_id=case_id, **payload.model_dump())
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return case_service.attach_owned_files(db, exam, "exam")


@router.put("/examinations/{exam_id}", response_model=schemas.MedicalExamination)
def update_examination(
    exam_id: int, payload: schemas.MedicalExaminationUpdate, db: Session = Depends(get_db)
):
    exam = db.get(models.MedicalExamination, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    for key, value in payload.model_dump().items():
        setattr(exam, key, value)
    db.commit()
    db.refresh(exam)
    return case_service.attach_owned_files(db, exam, "exam")


@router.delete("/examinations/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_examination(exam_id: int, db: Session = Depends(get_db)):
    exam = db.get(models.MedicalExamination, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    case_service.delete_owned_attachments(db, exam.case_id, "exam", exam.id)
    db.delete(exam)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# 处方
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/prescriptions",
    response_model=schemas.MedicalPrescription,
    status_code=status.HTTP_201_CREATED,
)
def create_prescription(
    case_id: int, payload: schemas.MedicalPrescriptionCreate, db: Session = Depends(get_db)
):
    _get_case_or_404(db, case_id)
    prescription = models.MedicalPrescription(
        case_id=case_id, **payload.model_dump(exclude={"drugs"})
    )
    case_service.apply_prescription_drugs(prescription, payload.drugs)
    db.add(prescription)
    db.commit()
    db.refresh(prescription)
    return case_service.attach_owned_files(db, prescription, "prescription")


@router.put("/prescriptions/{prescription_id}", response_model=schemas.MedicalPrescription)
def update_prescription(
    prescription_id: int,
    payload: schemas.MedicalPrescriptionUpdate,
    db: Session = Depends(get_db),
):
    prescription = db.get(models.MedicalPrescription, prescription_id)
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")
    for key, value in payload.model_dump(exclude={"drugs"}).items():
        setattr(prescription, key, value)
    case_service.apply_prescription_drugs(prescription, payload.drugs)
    db.commit()
    db.refresh(prescription)
    return case_service.attach_owned_files(db, prescription, "prescription")


@router.delete("/prescriptions/{prescription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prescription(prescription_id: int, db: Session = Depends(get_db)):
    prescription = db.get(models.MedicalPrescription, prescription_id)
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")
    case_service.delete_owned_attachments(db, prescription.case_id, "prescription", prescription.id)
    db.delete(prescription)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# 随访
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/follow_ups",
    response_model=schemas.MedicalFollowUp,
    status_code=status.HTTP_201_CREATED,
)
def create_follow_up(
    case_id: int, payload: schemas.MedicalFollowUpCreate, db: Session = Depends(get_db)
):
    _get_case_or_404(db, case_id)
    follow_up = models.MedicalFollowUp(case_id=case_id, **payload.model_dump())
    db.add(follow_up)
    db.commit()
    db.refresh(follow_up)
    return follow_up


@router.put("/follow_ups/{followup_id}", response_model=schemas.MedicalFollowUp)
def update_follow_up(
    followup_id: int, payload: schemas.MedicalFollowUpUpdate, db: Session = Depends(get_db)
):
    follow_up = db.get(models.MedicalFollowUp, followup_id)
    if not follow_up:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    for key, value in payload.model_dump().items():
        setattr(follow_up, key, value)
    db.commit()
    db.refresh(follow_up)
    return follow_up


@router.delete("/follow_ups/{followup_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_follow_up(followup_id: int, db: Session = Depends(get_db)):
    follow_up = db.get(models.MedicalFollowUp, followup_id)
    if not follow_up:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    db.delete(follow_up)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# 附件（仅保存/展示/下载，不做 OCR）
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/attachments",
    response_model=schemas.MedicalAttachment,
    status_code=status.HTTP_201_CREATED,
)
def upload_attachment(
    case_id: int,
    owner_type: str = Form(default="case"),
    owner_id: int | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    case = _get_case_or_404(db, case_id)
    if owner_type not in ("case", "exam", "prescription"):
        raise HTTPException(status_code=400, detail="owner_type 非法")

    if owner_type == "exam":
        exists = (
            db.query(models.MedicalExamination)
            .filter_by(id=owner_id, case_id=case_id)
            .first()
        )
        if owner_id is None or not exists:
            raise HTTPException(status_code=404, detail="检查不存在")
    elif owner_type == "prescription":
        exists = (
            db.query(models.MedicalPrescription)
            .filter_by(id=owner_id, case_id=case_id)
            .first()
        )
        if owner_id is None or not exists:
            raise HTTPException(status_code=404, detail="处方不存在")
    else:
        owner_id = None

    saved = save_upload(case.user_id, case_id, file)
    attachment = models.MedicalAttachment(
        case_id=case_id, owner_type=owner_type, owner_id=owner_id, **saved
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def _get_attachment_file(db: Session, attachment_id: int):
    attachment = db.get(models.MedicalAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = resolve_path(attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件缺失")
    return attachment, path


@router.get("/attachments/{attachment_id}/raw")
def get_attachment_raw(attachment_id: int, db: Session = Depends(get_db)):
    attachment, path = _get_attachment_file(db, attachment_id)
    return FileResponse(path, media_type=attachment.content_type or "application/octet-stream")


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment, path = _get_attachment_file(db, attachment_id)
    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.file_name,
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.get(models.MedicalAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在")
    db.delete(attachment)
    db.commit()
    return None
