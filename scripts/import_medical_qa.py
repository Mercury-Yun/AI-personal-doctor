#!/usr/bin/env python3
"""方案 A：把 medical-rag 风格 QA 数据转成 rag/*.md，供现有 FAISS RAG 使用。

用法:
  python scripts/import_medical_qa.py
  python scripts/import_medical_qa.py --source /path/to/huatuo.jsonl --max 200
  python scripts/import_medical_qa.py --dry-run

medical-rag 数据格式（JSON 数组或 JSONL，每行一条）:
  {"question": "...", "answer": "..."}

导入后请重启 API，或删除 backend/rag_cache/ 以重建索引。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "medical_qa_seed.jsonl"
RAG_DIR = ROOT / "rag" / "imported"

SKIP_TITLE_STEMS: set[str] = set()


def _load_existing_titles(rag_dir: Path) -> set[str]:
    titles: set[str] = set()
    if not rag_dir.exists():
        return titles
    for path in rag_dir.rglob("*.md"):
        SKIP_TITLE_STEMS.add(path.stem)
        text = path.read_text(encoding="utf-8").strip()
        first = text.splitlines()[0].strip() if text else ""
        if first.startswith("#"):
            titles.add(first.lstrip("#").strip())
    return titles


def _slug(text: str, max_len: int = 48) -> str:
    text = (text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", "", text)
    text = re.sub(r"\s+", "", text)
    if len(text) > max_len:
        text = text[:max_len]
    if text:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"qa_{digest}"


def _normalize_answer(answer: str) -> str:
    lines: list[str] = []
    for raw in (answer or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(
            r"^(定义|症状相关|注意事项|建议|用法相关|用法|禁忌|副作用)[：:]\s*",
            "",
            line,
        )
        if line:
            lines.append(line)
    merged = " ".join(lines) if lines else (answer or "").strip()
    merged = re.sub(r"\s+", " ", merged).strip()
    return merged


def _load_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return data if isinstance(data, list) else []
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            records.append(item)
    return records


def _to_markdown(question: str, answer: str) -> str:
    body = _normalize_answer(answer)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paragraphs:
        paragraphs = [body] if body else ["暂无补充说明。"]
    return f"# {question.strip()}\n\n" + "\n\n".join(paragraphs) + "\n"


def import_qa(
    source: Path,
    *,
    max_items: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    records = _load_records(source)
    existing_titles = _load_existing_titles(ROOT / "rag")
    seen_slugs: set[str] = set()
    written = skipped = 0

    for record in records:
        if written >= max_items:
            break
        question = (record.get("question") or record.get("summary") or "").strip()
        answer = (record.get("answer") or record.get("document") or "").strip()
        category = (record.get("category") or "qa").strip().lower()
        if not question or not answer:
            skipped += 1
            continue
        if question in existing_titles:
            skipped += 1
            continue

        slug_base = _slug(question)
        if category not in {"medicine", "disease", "elderly", "emergency", "qa"}:
            category = "qa"
        slug = slug_base
        suffix = 1
        while slug in seen_slugs or slug in SKIP_TITLE_STEMS:
            suffix += 1
            slug = f"{slug_base}_{suffix}"
        seen_slugs.add(slug)

        out_dir = RAG_DIR / category
        out_path = out_dir / f"{slug}.md"
        content = _to_markdown(question, answer)

        if dry_run:
            print(f"[dry-run] {out_path.relative_to(ROOT)} ({len(content)} bytes)")
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        written += 1

    return written, skipped, len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import medical QA into rag/imported/")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="JSON/JSONL 数据源")
    parser.add_argument("--max", type=int, default=120, help="最多导入条数（控制板端索引体积）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"数据源不存在: {args.source}")

    written, skipped, total = import_qa(args.source, max_items=args.max, dry_run=args.dry_run)
    print(f"完成: 写入 {written} 条, 跳过 {skipped} 条, 源文件共 {total} 条")
    if not args.dry_run and written:
        cache = ROOT / "backend" / "rag_cache"
        if cache.exists():
            for path in cache.glob("*"):
                path.unlink()
            print(f"已清空 {cache.relative_to(ROOT)}，重启 API 后将自动重建索引")


if __name__ == "__main__":
    main()
