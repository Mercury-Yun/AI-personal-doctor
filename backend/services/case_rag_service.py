"""Medical Case RAG：为「本人历史病例」建向量索引，供问诊时检索相关既往病例。

镜像 rag_service.py 的单例 + IndexFlatIP + 磁盘缓存形态，但：
- 缓存独立目录 backend/case_rag_cache/，与知识库索引隔离；
- 复用 rag_service 已加载的同一个 bge 模型（内存仅一份 ST 模型，RK3588 关键）；
- 文档=每病例一篇确定性结构化文本，不索引 LLM 摘要（廉价、可重建）；
- IndexFlatIP 无原生按 user 过滤，故超取 top_k*5 后按 user_id 后过滤。
"""

import hashlib
import json
import logging
from pathlib import Path
from threading import Lock

from .. import models
from .case_service import build_case_document
from .rag_service import get_rag_service

logger = logging.getLogger(__name__)


class CaseRAGService:
    def __init__(self):
        self.root_dir = Path(__file__).resolve().parents[2]
        self.cache_dir = self.root_dir / "backend" / "case_rag_cache"
        self.index_path = self.cache_dir / "index.faiss"
        self.meta_path = self.cache_dir / "chunks.json"
        self.index = None
        self.chunks = []
        self.signature = None
        self.lock = Lock()

    def initialize(self, db):
        """预热：构建（或加载）索引，供 main.py warmup 线程可选调用。"""
        self._ensure_index(db)

    def invalidate(self):
        """让下次 search 强制重建（供写操作触发懒重建）。"""
        with self.lock:
            self.index = None
            self.chunks = []
            self.signature = None

    def search(self, db, question, user_id, top_k=2):
        question = (question or "").strip()
        if not question:
            return []
        self._ensure_index(db)
        if self.index is None or not self.chunks:
            return []

        over = min(max(top_k * 5, top_k), len(self.chunks))
        query_vector = get_rag_service().embed([question])
        _, indexes = self.index.search(query_vector, over)
        results = []
        for idx in indexes[0]:
            if idx < 0 or idx >= len(self.chunks):
                continue
            chunk = self.chunks[idx]
            if user_id is not None and chunk.get("user_id") != user_id:
                continue
            results.append({"title": chunk["title"], "content": chunk["content"]})
            if len(results) >= top_k:
                break
        return results

    def _ensure_index(self, db):
        with self.lock:
            signature = self._signature(db)
            if self.index is not None and self.signature == signature:
                return

            documents = self._load_documents(db)
            if not documents:
                self.index = None
                self.chunks = []
                self.signature = signature
                return

            if self._load_cache(signature):
                return

            faiss = self._import_faiss()
            embeddings = get_rag_service().embed([item["content"] for item in documents])
            index = faiss.IndexFlatIP(embeddings.shape[1])
            index.add(embeddings)
            self.index = index
            self.chunks = documents
            self.signature = signature
            self._save_cache(signature)

    def _signature(self, db):
        rows = (
            db.query(models.MedicalCase.id, models.MedicalCase.updated_at)
            .order_by(models.MedicalCase.id.asc())
            .all()
        )
        payload = json.dumps(
            [[row[0], row[1].isoformat() if row[1] else ""] for row in rows],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_documents(self, db):
        cases = db.query(models.MedicalCase).order_by(models.MedicalCase.id.asc()).all()
        documents = []
        for case in cases:
            content = build_case_document(case)
            if not content.strip():
                continue
            title = " ".join(x for x in [case.visit_date, case.diagnosis or case.chief_complaint] if x)
            documents.append(
                {
                    "case_id": case.id,
                    "user_id": case.user_id,
                    "title": title.strip() or "病例",
                    "content": content,
                }
            )
        return documents

    def _load_cache(self, signature):
        if not self.index_path.exists() or not self.meta_path.exists():
            return False
        faiss = self._import_faiss()
        data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        if data.get("signature") != signature:
            return False
        self.index = faiss.read_index(str(self.index_path))
        self.chunks = data.get("chunks", [])
        self.signature = signature
        return True

    def _save_cache(self, signature):
        faiss = self._import_faiss()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_path))
        self.meta_path.write_text(
            json.dumps({"signature": signature, "chunks": self.chunks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _import_faiss(self):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is not installed") from exc
        return faiss


case_rag_service = CaseRAGService()


def get_case_rag_service():
    return case_rag_service
