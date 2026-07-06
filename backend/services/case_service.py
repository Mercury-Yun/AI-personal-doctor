import re

from .. import models, schemas


def compute_case_stats(db, user_id: int) -> dict:
    """病例统计：就诊次数/门诊次数/手术次数/过敏史数量。"""
    cases = (
        db.query(models.MedicalCase)
        .filter(models.MedicalCase.user_id == user_id)
        .all()
    )
    total = len(cases)
    outpatient = sum(1 for c in cases if (c.visit_type or "").strip() == "门诊")
    surgery = sum(1 for c in cases if (c.surgery_name or "").strip())

    user = db.get(models.User, user_id)
    allergy = 0
    if user and user.allergy:
        allergy = len([x for x in re.split(r"[、,，;；\n\s]+", user.allergy) if x.strip()])

    return {"total": total, "outpatient": outpatient, "surgery": surgery, "allergy": allergy}


def _owned_attachments(db, case_id: int, owner_type: str, owner_id: int):
    return (
        db.query(models.MedicalAttachment)
        .filter(
            models.MedicalAttachment.case_id == case_id,
            models.MedicalAttachment.owner_type == owner_type,
            models.MedicalAttachment.owner_id == owner_id,
        )
        .all()
    )


def attach_owned_files(db, obj, owner_type: str):
    """给单个检查/处方 ORM 挂上其附件（瞬态属性），供 response_model 序列化。"""
    obj.attachments = _owned_attachments(db, obj.case_id, owner_type, obj.id)
    return obj


def delete_owned_attachments(db, case_id: int, owner_type: str, owner_id: int) -> None:
    """删除某子实体名下的附件行（before_delete 事件同步清理磁盘文件）。"""
    for attachment in _owned_attachments(db, case_id, owner_type, owner_id):
        db.delete(attachment)


def apply_prescription_drugs(prescription, drugs) -> None:
    """整体替换处方药品清单（cascade delete-orphan 自动清理旧行）。"""
    prescription.drugs = [
        models.PrescriptionDrug(**drug.model_dump()) for drug in (drugs or [])
    ]


def to_case_detail(case) -> schemas.MedicalCaseDetail:
    """组装病例详情：把附件按 owner 归位到检查/处方/病例三层。"""
    grouped: dict[tuple[str, int], list] = {}
    case_level: list = []
    for att in case.attachments:
        if att.owner_type in ("exam", "prescription") and att.owner_id is not None:
            grouped.setdefault((att.owner_type, att.owner_id), []).append(att)
        else:
            case_level.append(att)

    for exam in case.examinations:
        exam.attachments = grouped.get(("exam", exam.id), [])
    for prescription in case.prescriptions:
        prescription.attachments = grouped.get(("prescription", prescription.id), [])

    detail = schemas.MedicalCaseDetail.model_validate(case)
    detail.attachments = [schemas.MedicalAttachment.model_validate(a) for a in case_level]
    return detail


def delete_case(db, case) -> None:
    """删除病例（cascade 删除检查/处方/随访/附件，附件文件由事件清理）。"""
    db.delete(case)
    db.commit()


def _short(text, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def build_case_document(case) -> str:
    """把单个病例压成确定性结构化文本，供 Case RAG 索引与 LLM 摘要复用。"""
    parts = []
    header = " ".join(
        x for x in [case.visit_date, case.visit_type, case.hospital, case.department, case.doctor] if x
    )
    if header:
        parts.append(f"就诊：{header}")
    if case.chief_complaint:
        parts.append(f"主诉：{case.chief_complaint}")
    if case.present_illness:
        parts.append(f"现病史：{case.present_illness}")
    if case.past_history:
        parts.append(f"既往史：{case.past_history}")
    if case.physical_exam:
        parts.append(f"体格检查：{case.physical_exam}")
    if case.diagnosis:
        parts.append(f"诊断：{case.diagnosis}")
    if case.doctor_advice:
        parts.append(f"医生建议：{case.doctor_advice}")
    if case.surgery_name:
        parts.append(f"手术：{case.surgery_name}")
    exams = [f"{e.name}（{e.result}）" if e.result else e.name for e in case.examinations if e.name]
    if exams:
        parts.append("检查：" + "；".join(exams))
    drugs = []
    for prescription in case.prescriptions:
        for drug in prescription.drugs:
            if drug.name:
                drugs.append(drug.name)
    if drugs:
        parts.append("处方：" + "、".join(dict.fromkeys(drugs)))
    return "\n".join(parts)


def build_case_digest(db, user_id: int) -> str:
    """患者级确定性病例摘要（最近就诊 + 最近诊断 + 条数），供 Prompt Builder 每轮注入。

    刻意只放少量关键行、不放整病例体，避免 token 膨胀与云端往返延迟。
    """
    cases = (
        db.query(models.MedicalCase)
        .filter(models.MedicalCase.user_id == user_id)
        .order_by(models.MedicalCase.visit_date.desc(), models.MedicalCase.id.desc())
        .all()
    )
    if not cases:
        return ""

    lines = ["【病例摘要】", f"病例条数：{len(cases)} 条"]
    latest = cases[0]
    visit_bits = [x for x in [latest.visit_date, latest.visit_type, latest.hospital, latest.department] if x]
    visit_line = " ".join(visit_bits)
    if latest.chief_complaint:
        complaint = _short(latest.chief_complaint, 40)
        visit_line = f"{visit_line}（主诉：{complaint}）" if visit_line else f"主诉：{complaint}"
    if visit_line.strip():
        lines.append(f"最近就诊：{visit_line.strip()}")

    diag_case = next((c for c in cases if (c.diagnosis or "").strip()), None)
    if diag_case:
        lines.append(f"最近诊断：{_short(diag_case.diagnosis, 60)}")
    advice_case = next((c for c in cases if (c.doctor_advice or "").strip()), None)
    if advice_case:
        lines.append(f"医生建议：{_short(advice_case.doctor_advice, 60)}")
    return "\n".join(lines)
