from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json

from .. import schemas
from ..database import get_db
from ..services.chat_service import (
    answer_question,
    create_chat_session,
    delete_chat_session,
    get_chat_history,
    get_recent_sessions,
    list_chat_sessions,
    stream_answer_question,
    stream_vision_answer_question,
    update_chat_session_title,
    voice_question,
)
from ..services.medicine_service import identify_medicine
from ..services.rag_service import get_rag_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=schemas.ChatResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    try:
        return answer_question(
            db, request.session_id, request.user_id, request.question, speak=request.speak
        )
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/stream")
def chat_stream(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    def event_generator():
        try:
            for event in stream_answer_question(
                db,
                request.session_id,
                request.user_id,
                request.question,
                speak=request.speak,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except HTTPException as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': exc.detail}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/vision/stream")
def chat_vision_stream(request: schemas.ChatVisionRequest, db: Session = Depends(get_db)):
    def event_generator():
        try:
            for event in stream_vision_answer_question(
                db,
                request.session_id,
                request.user_id,
                request.question,
                speak=request.speak,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except HTTPException as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': exc.detail}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/medicine/identify", response_model=schemas.MedicineIdentifyResponse)
def medicine_identify(request: schemas.MedicineIdentifyRequest):
    try:
        return identify_medicine()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/voice", response_model=schemas.ChatResponse)
def chat_voice(request: schemas.ChatVoiceRequest, db: Session = Depends(get_db)):
    try:
        return voice_question(db, request.session_id, request.user_id, speak=request.speak)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/chat/sessions/{user_id}", response_model=list[schemas.ChatSessionItem])
def sessions(user_id: int, db: Session = Depends(get_db)):
    return list_chat_sessions(db, user_id)


@router.post("/chat/session", response_model=schemas.ChatSessionItem)
def create_session(request: schemas.ChatSessionCreate, db: Session = Depends(get_db)):
    return create_chat_session(db, request.user_id)


@router.put("/chat/session/{session_id}", response_model=schemas.ChatSessionItem)
def rename_session(session_id: int, request: schemas.ChatSessionUpdate, db: Session = Depends(get_db)):
    return update_chat_session_title(db, session_id, request.title)


@router.delete("/chat/session/{session_id}")
def remove_session(session_id: int, db: Session = Depends(get_db)):
    delete_chat_session(db, session_id)
    return {"status": "ok"}


@router.get("/chat/history/{session_id}", response_model=list[schemas.ChatHistoryItem])
def history(session_id: int, db: Session = Depends(get_db)):
    return get_chat_history(db, session_id)


@router.get("/chat/recent", response_model=list[schemas.ChatSessionItem])
def recent(limit: int = Query(default=5, ge=1, le=20), db: Session = Depends(get_db)):
    return get_recent_sessions(db, limit)


@router.post("/search_knowledge", response_model=schemas.KnowledgeSearchResponse)
def search_knowledge(request: schemas.KnowledgeSearchRequest):
    try:
        results = get_rag_service().search(request.question, top_k=3)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"results": results}
