import re
from datetime import datetime

from sqlalchemy import inspect, text

from .database import engine, SessionLocal
from . import models


def run_startup_migrations():
    _ensure_chat_session_schema()
    _ensure_medication_reminder_schema()
    _ensure_medication_take_times_schema()
    _ensure_user_blood_type_schema()
    _ensure_user_chronic_diseases_schema()
    _backfill_chronic_diseases_from_records()
    _migrate_legacy_chat_history()


def _ensure_user_chronic_diseases_schema():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "chronic_diseases" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN chronic_diseases TEXT"))


def _backfill_chronic_diseases_from_records():
    """从旧 medical_records 聚合去重慢病标签回填 users.chronic_diseases。

    仅当 users.chronic_diseases 为空时回填，幂等；用原始 SQL 读旧表，
    不依赖旧 ORM 模型仍然存在。
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "users" not in table_names or "medical_records" not in table_names:
        return

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, chronic_disease FROM medical_records "
                "WHERE chronic_disease IS NOT NULL AND TRIM(chronic_disease) != ''"
            )
        ).fetchall()
        if not rows:
            return

        aggregated: dict[int, list[str]] = {}
        for user_id, disease in rows:
            bucket = aggregated.setdefault(user_id, [])
            for token in re.split(r"[、,，;；\n\s]+", disease or ""):
                token = token.strip()
                if token and token not in bucket:
                    bucket.append(token)

        for user_id, diseases in aggregated.items():
            if not diseases:
                continue
            current = connection.execute(
                text("SELECT chronic_diseases FROM users WHERE id = :uid"),
                {"uid": user_id},
            ).scalar()
            if current and current.strip():
                continue
            connection.execute(
                text("UPDATE users SET chronic_diseases = :val WHERE id = :uid"),
                {"val": "、".join(diseases), "uid": user_id},
            )


def _ensure_user_blood_type_schema():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "blood_type" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN blood_type TEXT"))


def _ensure_medication_take_times_schema():
    inspector = inspect(engine)
    if "medications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("medications")}
    if "take_times" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE medications ADD COLUMN take_times TEXT"))

    db = SessionLocal()
    try:
        medications = db.query(models.Medication).all()
        changed = False
        for medication in medications:
            if medication.take_times:
                continue
            legacy = (medication.take_time or "").strip()
            if not legacy:
                continue
            medication.take_times = f'["{legacy}"]'
            changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def _ensure_medication_reminder_schema():
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "medication_reminder_logs" not in table_names:
        models.MedicationReminderLog.__table__.create(bind=engine, checkfirst=True)


def _ensure_chat_session_schema():
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "chat_sessions" not in table_names:
        models.ChatSession.__table__.create(bind=engine, checkfirst=True)

    chat_columns = {column["name"] for column in inspector.get_columns("chat_history")} if "chat_history" in table_names else set()
    if "chat_history" in table_names and "session_id" not in chat_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE chat_history ADD COLUMN session_id INTEGER"))


def _migrate_legacy_chat_history():
    db = SessionLocal()
    try:
        legacy_user_ids = [
            row[0]
            for row in db.query(models.ChatHistory.user_id)
            .filter(models.ChatHistory.session_id.is_(None))
            .distinct()
            .all()
        ]

        for user_id in legacy_user_ids:
            first_message = (
                db.query(models.ChatHistory)
                .filter(models.ChatHistory.user_id == user_id, models.ChatHistory.role == "user")
                .order_by(models.ChatHistory.created_at.asc(), models.ChatHistory.id.asc())
                .first()
            )
            title = _build_session_title(first_message.content if first_message else "历史问诊")
            session = models.ChatSession(user_id=user_id, title=title, updated_at=datetime.now())
            db.add(session)
            db.flush()

            (
                db.query(models.ChatHistory)
                .filter(models.ChatHistory.user_id == user_id, models.ChatHistory.session_id.is_(None))
                .update({models.ChatHistory.session_id: session.id}, synchronize_session=False)
            )
        db.commit()
    finally:
        db.close()


def _build_session_title(content):
    title = (content or "").strip()[:20]
    return title or "新问诊"
