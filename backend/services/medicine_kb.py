"""解析 rag/medicine/*.md 结构化用药知识库，供拍照识药按字段取用。

与 RAG 向量检索相互独立：RAG 负责语义检索文本片段，这里负责把同一批
Markdown 逐字段解析成结构化记录（名称/别名/规格/类别/治疗用途/用法用量/注意事项），
按识别出的药名精确匹配，避免 VLM 生成信息不稳定或产生幻觉。
"""

import re
from pathlib import Path
from threading import Lock

FIELD_ALIASES = "别名"
FIELD_SPEC = "规格"
FIELD_CATEGORY = "类别"
FIELD_USES = "治疗用途"
FIELD_USAGE = "用法用量"
FIELD_CAUTIONS = "注意事项"

# 去除剂型后缀时按“长后缀优先”排序，避免“缓释片”被“片”提前截断
_DOSAGE_SUFFIXES = [
    "缓释胶囊", "缓释片", "肠溶胶囊", "肠溶片", "分散片", "咀嚼片",
    "软胶囊", "泡腾片", "口服液", "口服溶液", "混悬液", "注射液",
    "气雾剂", "喷雾剂", "滴眼液", "眼膏", "软膏", "凝胶",
    "胶囊", "颗粒", "滴剂", "喷剂", "乳膏", "栓剂",
    "散剂", "散", "片", "丸", "膏", "栓", "水",
]


class MedicineKB:
    def __init__(self):
        self.root_dir = Path(__file__).resolve().parents[2]
        self.kb_dir = self.root_dir / "rag" / "medicine"
        self.records = []
        self._signature = None
        self.lock = Lock()

    def _current_signature(self) -> str:
        if not self.kb_dir.exists():
            return ""
        entries = []
        for path in sorted(self.kb_dir.glob("*.md")):
            stat = path.stat()
            entries.append(f"{path.name}:{stat.st_mtime}:{stat.st_size}")
        return "|".join(entries)

    def _ensure_loaded(self) -> None:
        with self.lock:
            signature = self._current_signature()
            if signature == self._signature and self.records:
                return
            self.records = self._load()
            self._signature = signature

    def _load(self) -> list:
        records = []
        if not self.kb_dir.exists():
            return records
        for path in sorted(self.kb_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            record = self._parse(text, path)
            if record:
                records.append(record)
        return records

    def _parse(self, text: str, path: Path) -> dict:
        name = path.stem
        aliases: list[str] = []
        spec = ""
        category = ""
        uses = ""
        usage = ""
        cautions: list[str] = []
        current_field = None

        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                name = stripped[2:].strip() or name
                current_field = None
                continue

            match = re.match(r"^-\s*([^：:]+)[：:]\s*(.*)$", stripped)
            if match:
                field = match.group(1).strip()
                value = match.group(2).strip()
                current_field = field
                if field == FIELD_ALIASES:
                    aliases = [a.strip() for a in re.split(r"[、,，]", value) if a.strip()]
                elif field == FIELD_SPEC:
                    spec = value
                elif field == FIELD_CATEGORY:
                    category = value
                elif field == FIELD_USES:
                    uses = value
                elif field == FIELD_USAGE:
                    usage = value
                elif field == FIELD_CAUTIONS and value:
                    cautions.append(value)
                continue

            # 续行：注意事项编号列表，或治疗用途/用法用量换行续写
            if current_field == FIELD_CAUTIONS:
                item = re.sub(r"^\d+\s*[\.、]\s*", "", stripped)
                item = re.sub(r"^[-*]\s*", "", item)
                if item:
                    cautions.append(item)
            elif current_field == FIELD_USES:
                uses += stripped
            elif current_field == FIELD_USAGE:
                usage += stripped

        return {
            "name": name,
            "aliases": aliases,
            "spec": spec,
            "category": category,
            "uses": uses,
            "usage": usage,
            "cautions": cautions,
            "source": str(path.relative_to(self.root_dir)),
        }

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\s()（）\[\]【】·・\-—]", "", (text or "")).strip()

    def _core(self, text: str) -> str:
        core = self._normalize(text)
        for suffix in _DOSAGE_SUFFIXES:
            if core.endswith(suffix) and len(core) > len(suffix):
                return core[: -len(suffix)]
        return core

    def match(self, recognized_name: str, raw_text: str = "") -> dict | None:
        self._ensure_loaded()
        if not self.records:
            return None
        candidates = [c for c in (recognized_name, raw_text) if c]
        norm_candidates = [n for n in (self._normalize(c) for c in candidates) if n]
        if not norm_candidates:
            return None

        # 1. 名称/别名精确匹配
        for record in self.records:
            norm_names = [self._normalize(n) for n in [record["name"], *record["aliases"]]]
            if any(nc in norm_names for nc in norm_candidates):
                return record

        # 2. 名称/别名互相包含（取匹配名最长者，减少误命中）
        best = None
        best_len = 0
        for record in self.records:
            for name in [record["name"], *record["aliases"]]:
                norm_name = self._normalize(name)
                if len(norm_name) < 2:
                    continue
                for nc in norm_candidates:
                    if (norm_name in nc or nc in norm_name) and len(norm_name) > best_len:
                        best = record
                        best_len = len(norm_name)
        if best:
            return best

        # 3. 去剂型后缀的核心名匹配
        cand_cores = {c for c in (self._core(c) for c in candidates) if len(c) >= 2}
        for record in self.records:
            rec_cores = {c for c in (self._core(n) for n in [record["name"], *record["aliases"]]) if len(c) >= 2}
            if cand_cores & rec_cores:
                return record
            for rec_core in rec_cores:
                for cand_core in cand_cores:
                    if rec_core in cand_core or cand_core in rec_core:
                        return record
        return None


medicine_kb = MedicineKB()


def get_medicine_kb() -> MedicineKB:
    return medicine_kb
