import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

ATTACHMENTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "attachments"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _guess_kind(ext: str) -> str:
    return "image" if ext in IMAGE_EXTENSIONS else "pdf"


def save_upload(user_id: int, case_id: int, upload: UploadFile) -> dict:
    """保存上传文件到 data/attachments/{user_id}/{case_id}/{uuid}.{ext}，仅存储不解析。"""
    original_name = (upload.filename or "attachment").strip() or "attachment"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext or '未知'}")

    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件过大（上限 10MB）")

    target_dir = ATTACHMENTS_DIR / str(user_id) / str(case_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / stored_name).write_bytes(data)

    return {
        "file_name": original_name,
        "stored_path": f"{user_id}/{case_id}/{stored_name}",
        "content_type": upload.content_type or "",
        "size": len(data),
        "kind": _guess_kind(ext),
    }


def resolve_path(stored_path: str) -> Path:
    """把相对 stored_path 还原为绝对路径，并阻止路径穿越。"""
    stored = (stored_path or "").strip().lstrip("/")
    base = ATTACHMENTS_DIR.resolve()
    candidate = (ATTACHMENTS_DIR / stored).resolve()
    if base != candidate and base not in candidate.parents:
        raise HTTPException(status_code=404, detail="附件不存在")
    return candidate
