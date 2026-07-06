import hashlib
import json
import os
from pathlib import Path
from threading import Lock


class RAGService:
    def __init__(self):
        self.root_dir = Path(__file__).resolve().parents[2]
        self.rag_dir = self.root_dir / "rag"
        self.cache_dir = self.root_dir / "backend" / "rag_cache"
        self.index_path = self.cache_dir / "index.faiss"
        self.meta_path = self.cache_dir / "chunks.json"
        self.model_name = "BAAI/bge-small-zh-v1.5"
        self.model = None
        self.index = None
        self.chunks = []
        self.initialized = False
        self.lock = Lock()

    def initialize(self):
        with self.lock:
            if self.initialized:
                return

            documents = self._load_documents()
            if not documents:
                self.chunks = []
                self.index = None
                self.initialized = True
                return

            signature = self._signature()
            if self._load_cache(signature):
                self.preload_model()
                self.initialized = True
                return

            faiss = self._import_faiss()
            embeddings = self._embed([item["content"] for item in documents])
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)
            self.index.add(embeddings)
            self.chunks = documents
            self._save_cache(signature)
            self.preload_model()
            self.initialized = True

    def search(self, question, top_k=3):
        if not self.initialized:
            self.initialize()
        if self.index is None or not self.chunks:
            return []

        query_vector = self._embed([question])
        scores, indexes = self.index.search(query_vector, top_k)
        results = []
        for index in indexes[0]:
            if index < 0 or index >= len(self.chunks):
                continue
            chunk = self.chunks[index]
            results.append({"title": chunk["title"], "content": chunk["content"]})
        return results

    def _load_documents(self):
        documents = []
        if not self.rag_dir.exists():
            return documents

        for path in sorted(self.rag_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            title = path.stem
            for index, chunk in enumerate(self._split_text(text)):
                documents.append({
                    "id": f"{path.relative_to(self.rag_dir).as_posix()}#{index}",
                    "title": title,
                    "content": chunk,
                    "source": str(path.relative_to(self.root_dir)),
                })
        return documents

    def _split_text(self, text, chunk_size=520, overlap=80):
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(normalized) <= chunk_size:
            return [normalized]

        chunks = []
        start = 0
        while start < len(normalized):
            end = start + chunk_size
            chunks.append(normalized[start:end])
            if end >= len(normalized):
                break
            start = max(0, end - overlap)
        return chunks

    def _signature(self):
        entries = []
        if self.rag_dir.exists():
            for path in sorted(self.rag_dir.rglob("*.md")):
                stat = path.stat()
                entries.append({
                    "path": path.relative_to(self.rag_dir).as_posix(),
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                })
        payload = json.dumps(entries, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_cache(self, signature):
        if not self.index_path.exists() or not self.meta_path.exists():
            return False

        faiss = self._import_faiss()
        data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        if data.get("signature") != signature:
            return False

        self.index = faiss.read_index(str(self.index_path))
        self.chunks = data.get("chunks", [])
        return True

    def preload_model(self):
        if self.index is None:
            return
        self._get_model()
        self._embed(["预热"])

    def _save_cache(self, signature):
        faiss = self._import_faiss()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_path))
        self.meta_path.write_text(
            json.dumps({"signature": signature, "chunks": self.chunks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def embed(self, texts):
        """公开的向量化入口，供 Case RAG 复用同一个 bge 模型（内存仅一份）。"""
        return self._embed(texts)

    def _embed(self, texts):
        import numpy as np

        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype="float32")

    def _get_model(self):
        if self.model is None:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is not installed") from exc
            self.model = SentenceTransformer(self.model_name)
        return self.model

    def _import_faiss(self):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is not installed") from exc
        return faiss


rag_service = RAGService()


def get_rag_service():
    return rag_service
