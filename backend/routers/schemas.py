from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    phone: Optional[str] = None
    emergency_contact: Optional[str] = None
    emergency_phone: Optional[str] = None
    allergy: Optional[str] = None
    remark: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserUpdate(UserBase):
    pass


class User(UserBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicalRecordBase(BaseModel):
    user_id: int
    chronic_disease: Optional[str] = None
    history: Optional[str] = None
    current_symptom: Optional[str] = None
    medicine: Optional[str] = None
    doctor_advice: Optional[str] = None


class MedicalRecordCreate(MedicalRecordBase):
    pass


class MedicalRecordUpdate(MedicalRecordBase):
    pass


class MedicalRecord(MedicalRecordBase):
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
