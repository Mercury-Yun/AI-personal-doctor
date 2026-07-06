from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text, event
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    age = Column(Integer)
    gender = Column(Text)
    height = Column(Float)
    weight = Column(Float)
    blood_type = Column(Text)
    phone = Column(Text)
    emergency_contact = Column(Text)
    emergency_phone = Column(Text)
    allergy = Column(Text)
    remark = Column(Text)
    chronic_diseases = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    medications = relationship("Medication", back_populates="user", cascade="all, delete")
    chats = relationship("ChatHistory", back_populates="user", cascade="all, delete")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete")
    cases = relationship("MedicalCase", back_populates="user", cascade="all, delete")


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(Text, nullable=False)
    dosage = Column(Text)
    frequency = Column(Text)
    take_time = Column(Text)
    take_times = Column(Text)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="medications")
    reminder_logs = relationship("MedicationReminderLog", back_populates="medication", cascade="all, delete")


class MedicationReminderLog(Base):
    __tablename__ = "medication_reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    schedule_date = Column(Text, nullable=False)
    schedule_time = Column(Text, nullable=False)
    notified_at = Column(DateTime)
    taken_at = Column(DateTime)
    status = Column(Text, nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.now)

    medication = relationship("Medication", back_populates="reminder_logs")
    user = relationship("User")


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="chats")
    session = relationship("ChatSession", back_populates="messages")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(Text, nullable=False, default="新问诊")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatHistory", back_populates="session", cascade="all, delete")


class GarminDaily(Base):
    """佳明手表每日健康快照（一天一行，账号级，不区分患者）。"""

    __tablename__ = "garmin_daily"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Text, nullable=False, unique=True, index=True)  # YYYY-MM-DD
    resting_hr = Column(Integer)
    max_hr = Column(Integer)
    min_hr = Column(Integer)
    steps = Column(Integer)
    sleep_seconds = Column(Integer)
    avg_stress = Column(Integer)
    avg_spo2 = Column(Integer)
    lowest_spo2 = Column(Integer)
    body_battery = Column(Integer)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=datetime.now)


class MedicalCase(Base):
    """一次就诊 = 一个病例，病例管理 V2 的聚合根。"""

    __tablename__ = "medical_cases"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    visit_date = Column(Text)  # YYYY-MM-DD
    visit_type = Column(Text)  # 门诊/住院/急诊
    hospital = Column(Text)
    department = Column(Text)
    doctor = Column(Text)
    chief_complaint = Column(Text)   # 主诉
    present_illness = Column(Text)   # 现病史
    past_history = Column(Text)      # 既往史
    physical_exam = Column(Text)     # 体格检查
    diagnosis = Column(Text)         # 临床诊断
    doctor_advice = Column(Text)     # 医生建议
    doctor_note = Column(Text)       # 医生备注
    surgery_name = Column(Text)      # 手术名称（可选）
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="cases")
    examinations = relationship(
        "MedicalExamination", back_populates="case", cascade="all, delete-orphan"
    )
    prescriptions = relationship(
        "MedicalPrescription", back_populates="case", cascade="all, delete-orphan"
    )
    follow_ups = relationship(
        "MedicalFollowUp", back_populates="case", cascade="all, delete-orphan"
    )
    attachments = relationship(
        "MedicalAttachment", back_populates="case", cascade="all, delete-orphan"
    )


class MedicalExamination(Base):
    __tablename__ = "medical_examinations"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("medical_cases.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    exam_time = Column(Text)  # YYYY-MM-DD
    hospital = Column(Text)
    result = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    case = relationship("MedicalCase", back_populates="examinations")


class MedicalPrescription(Base):
    __tablename__ = "medical_prescriptions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("medical_cases.id"), nullable=False, index=True)
    issued_date = Column(Text)  # YYYY-MM-DD
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    case = relationship("MedicalCase", back_populates="prescriptions")
    drugs = relationship(
        "PrescriptionDrug", back_populates="prescription", cascade="all, delete-orphan"
    )


class PrescriptionDrug(Base):
    __tablename__ = "prescription_drugs"

    id = Column(Integer, primary_key=True, index=True)
    prescription_id = Column(
        Integer, ForeignKey("medical_prescriptions.id"), nullable=False, index=True
    )
    name = Column(Text, nullable=False)
    dosage = Column(Text)
    usage = Column(Text)
    frequency = Column(Text)
    duration = Column(Text)

    prescription = relationship("MedicalPrescription", back_populates="drugs")


class MedicalFollowUp(Base):
    __tablename__ = "medical_follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("medical_cases.id"), nullable=False, index=True)
    follow_date = Column(Text)  # YYYY-MM-DD
    advice = Column(Text)
    recovery = Column(Text)
    completed = Column(Integer, default=0)
    next_plan = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    case = relationship("MedicalCase", back_populates="follow_ups")


class MedicalAttachment(Base):
    """病例附件（检查图片/PDF、处方图片）。仅保存文件，不做 OCR。"""

    __tablename__ = "medical_attachments"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("medical_cases.id"), nullable=False, index=True)
    owner_type = Column(Text, nullable=False)  # case/exam/prescription
    owner_id = Column(Integer, index=True)
    file_name = Column(Text, nullable=False)
    stored_path = Column(Text, nullable=False)  # 相对 data/attachments
    content_type = Column(Text)
    size = Column(Integer)
    kind = Column(Text)  # image/pdf
    created_at = Column(DateTime, default=datetime.now)

    case = relationship("MedicalCase", back_populates="attachments")


@event.listens_for(MedicalAttachment, "before_delete")
def _remove_attachment_file(mapper, connection, target):
    """删除附件行时同步删除磁盘文件，覆盖直接删附件与级联删病例两条路径。"""
    stored = (target.stored_path or "").strip()
    if not stored:
        return
    file_path = Path(__file__).resolve().parent.parent / "data" / "attachments" / stored
    try:
        if file_path.is_file():
            file_path.unlink()
    except OSError:
        pass
