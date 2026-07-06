from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None
    emergency_contact: Optional[str] = None
    emergency_phone: Optional[str] = None
    allergy: Optional[str] = None
    remark: Optional[str] = None
    chronic_diseases: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserUpdate(UserBase):
    pass


class User(UserBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationBase(BaseModel):
    user_id: int
    name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    take_time: Optional[str] = None
    take_times: list[str] = []
    note: Optional[str] = None


class MedicationCreate(MedicationBase):
    pass


class MedicationUpdate(MedicationBase):
    pass


class Medication(MedicationBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 病例管理 V2
# ---------------------------------------------------------------------------


class MedicalAttachment(BaseModel):
    id: int
    case_id: int
    owner_type: str
    owner_id: Optional[int] = None
    file_name: str
    content_type: Optional[str] = None
    size: Optional[int] = None
    kind: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PrescriptionDrugBase(BaseModel):
    name: str
    dosage: Optional[str] = None
    usage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None


class PrescriptionDrugCreate(PrescriptionDrugBase):
    pass


class PrescriptionDrug(PrescriptionDrugBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MedicalExaminationBase(BaseModel):
    name: str
    exam_time: Optional[str] = None
    hospital: Optional[str] = None
    result: Optional[str] = None


class MedicalExaminationCreate(MedicalExaminationBase):
    pass


class MedicalExaminationUpdate(MedicalExaminationBase):
    pass


class MedicalExamination(MedicalExaminationBase):
    id: int
    case_id: int
    created_at: datetime
    attachments: list[MedicalAttachment] = []

    model_config = ConfigDict(from_attributes=True)


class MedicalPrescriptionBase(BaseModel):
    issued_date: Optional[str] = None
    note: Optional[str] = None


class MedicalPrescriptionCreate(MedicalPrescriptionBase):
    drugs: list[PrescriptionDrugCreate] = []


class MedicalPrescriptionUpdate(MedicalPrescriptionBase):
    drugs: list[PrescriptionDrugCreate] = []


class MedicalPrescription(MedicalPrescriptionBase):
    id: int
    case_id: int
    created_at: datetime
    drugs: list[PrescriptionDrug] = []
    attachments: list[MedicalAttachment] = []

    model_config = ConfigDict(from_attributes=True)


class MedicalFollowUpBase(BaseModel):
    follow_date: Optional[str] = None
    advice: Optional[str] = None
    recovery: Optional[str] = None
    completed: int = 0
    next_plan: Optional[str] = None


class MedicalFollowUpCreate(MedicalFollowUpBase):
    pass


class MedicalFollowUpUpdate(MedicalFollowUpBase):
    pass


class MedicalFollowUp(MedicalFollowUpBase):
    id: int
    case_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicalCaseBase(BaseModel):
    visit_date: Optional[str] = None
    visit_type: Optional[str] = None
    hospital: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    chief_complaint: Optional[str] = None
    present_illness: Optional[str] = None
    past_history: Optional[str] = None
    physical_exam: Optional[str] = None
    diagnosis: Optional[str] = None
    doctor_advice: Optional[str] = None
    doctor_note: Optional[str] = None
    surgery_name: Optional[str] = None


class MedicalCaseCreate(MedicalCaseBase):
    user_id: int


class MedicalCaseUpdate(MedicalCaseBase):
    pass


class MedicalCaseListItem(BaseModel):
    id: int
    user_id: int
    visit_date: Optional[str] = None
    visit_type: Optional[str] = None
    hospital: Optional[str] = None
    department: Optional[str] = None
    chief_complaint: Optional[str] = None
    doctor: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MedicalCaseDetail(MedicalCaseBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    examinations: list[MedicalExamination] = []
    prescriptions: list[MedicalPrescription] = []
    follow_ups: list[MedicalFollowUp] = []
    attachments: list[MedicalAttachment] = []

    model_config = ConfigDict(from_attributes=True)


class CaseStats(BaseModel):
    total: int
    outpatient: int
    surgery: int
    allergy: int


class CaseSummary(BaseModel):
    main_disease: str = ""
    history: str = ""
    recent_visit: str = ""
    recent_exam: str = ""
    current_treatment: str = ""
    doctor_advice: str = ""
    follow_up: str = ""
    risk: list[str] = []


class DashboardStats(BaseModel):
    userCount: int
    recordCount: int
    medicationCount: int
    reminderCount: int


class HealthProfileInsight(BaseModel):
    name: str
    age: Optional[int] = None
    chronicCount: int
    medicationCount: int
    risk: str
    suggestions: list[str]


class KnowledgeSearchRequest(BaseModel):
    question: str


class KnowledgeResult(BaseModel):
    title: str
    content: str


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeResult]


class ChatRequest(BaseModel):
    session_id: int
    user_id: int
    question: str
    speak: bool = False


class ChatSessionCreate(BaseModel):
    user_id: int


class ChatSessionUpdate(BaseModel):
    title: str


class ChatSessionItem(BaseModel):
    id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryItem(BaseModel):
    id: int
    user_id: int
    session_id: Optional[int] = None
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    answer: str
    references: list[KnowledgeResult]
    prompt: str
    source: str | None = None
    question: str | None = None


class ChatVoiceRequest(BaseModel):
    session_id: int
    user_id: int
    speak: bool = True


class DeviceStatusResponse(BaseModel):
    online: bool
    demo_busy: bool = False
    capture_active: bool = False
    photo_mode: bool = False
    photo_mode_preparing: bool = False
    photo_mode_ready: bool = False
    voice_mode: bool = False
    tts_enabled: bool | None = None
    tts_source: str | None = None
    tts_busy: bool = False
    tts_playing: bool = False
    demo_url: str
    error: str | None = None


class DeviceSpeakRequest(BaseModel):
    text: str
    wait: bool = False


class DeviceListenRequest(BaseModel):
    prompt: bool = False
    speak_first: str = ""


class IntentClassifyRequest(BaseModel):
    text: str


class IntentClassifyResponse(BaseModel):
    ok: bool = True
    intent: str
    text: str


class PhotoSessionIntentRequest(BaseModel):
    text: str
    has_photo: bool = False


class PhotoSessionIntentResponse(BaseModel):
    ok: bool = True
    action: str
    text: str


class DeviceCameraCaptureResponse(BaseModel):
    ok: bool = True
    width: int
    height: int
    path: str | None = None


class WakeInfoResponse(BaseModel):
    ok: bool = True
    enabled: bool = False
    kws_enabled: bool = False
    wake_word: str = "小医"
    listening: bool = False
    error: str | None = None


class WakeSessionResponse(BaseModel):
    ok: bool = True
    wake_word: str
    intent: str = "chat"
    text: str = ""
    user_id: int
    needs_listen: bool = False
    photo_prep: bool = False


class ChatVisionRequest(BaseModel):
    session_id: int
    user_id: int
    question: str = ""
    speak: bool = True


class MedicineIdentifyRequest(BaseModel):
    user_id: Optional[int] = None
    session_id: Optional[int] = None


class MedicineIdentifyResponse(BaseModel):
    ok: bool = True
    matched: bool = False
    recognized_name: str = ""
    spec: str = ""
    name: str = ""
    category: str = ""
    uses: str = ""
    usage: str = ""
    cautions: list[str] = []
    source: str = ""
    note: str = ""


class TodayReminderItem(BaseModel):
    medication_id: int
    user_id: int
    user_name: str
    name: str
    dosage: str | None = None
    frequency: str | None = None
    take_time: str
    dose_index: int = 1
    dose_total: int = 1
    note: str | None = None
    status: str
    notified_at: str | None = None
    taken_at: str | None = None
