#!/usr/bin/env python3
"""AI 问诊 + RAG 性能 benchmark 脚本。

测试内容：
  - RAG 建库时间、检索时间、Top1/Top3 命中率
  - AI 问诊 TTFT、Tokens/sec、总耗时、Prompt/回复长度

用法:
  cd /path/to/AI-Personal-Doctor
  python scripts/benchmark_chat.py
"""

from __future__ import annotations

import sys
import os

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_chat.py

import time
import threading
import traceback
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import SessionLocal
from backend.services.rag_service import get_rag_service
from backend.services.cloud_llm_service import cloud_configured
from backend.services.chat_service import (
    create_chat_session,
    stream_answer_question,
)
from backend import models

# ============================================================
# 测试问题列表
# ============================================================
TEST_QUESTIONS = [
    "我最近头晕三天了，有高血压，怎么办？",
    "感冒发烧38.5度，可以吃什么药？",
    "糖尿病患者饮食要注意什么？",
    "最近总是失眠，有什么好的建议吗？",
    "高血压可以吃阿司匹林吗？",
    "腰酸背痛是什么原因？",
    "血糖偏高需要吃药吗？",
    "老年人应该多久做一次体检？",
    "胃疼吃什么药好？",
    "高血压低压高是怎么回事？",
]

# 用于检查检索命中率的关键词映射（问题索引 -> 期望命中的关键词列表）
RELEVANCE_KEYWORDS: dict[int, list[str]] = {
    0: ["头晕", "高血压", "血压"],
    1: ["感冒", "发烧", "退烧", "发热"],
    2: ["糖尿病", "饮食", "血糖"],
    3: ["失眠", "睡眠", "助眠"],
    4: ["高血压", "阿司匹林", "抗血小板"],
    5: ["腰", "背", "脊椎", "疼痛", "腰痛"],
    6: ["血糖", "糖尿病", "降糖"],
    7: ["体检", "老年", "检查"],
    8: ["胃", "胃痛", "胃疼", "消化"],
    9: ["高血压", "低压", "舒张压"],
}


# ============================================================
# 内存监控线程
# ============================================================
class MemoryMonitor:
    """后台线程定期采集当前进程 RSS 内存（MB）。"""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_mb: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        return self.peak_mb

    def _run(self):
        try:
            import psutil
            proc = psutil.Process()
            while not self._stop.is_set():
                rss = proc.memory_info().rss / (1024 * 1024)
                if rss > self.peak_mb:
                    self.peak_mb = rss
                self._stop.wait(self.interval)
        except ImportError:
            # psutil 不可用，尝试从 /proc 读取
            import os
            pid = os.getpid()
            while not self._stop.is_set():
                try:
                    with open(f"/proc/{pid}/status") as f:
                        for line in f:
                            if line.startswith("VmRSS:"):
                                rss_kb = int(line.split()[1])
                                rss_mb = rss_kb / 1024
                                if rss_mb > self.peak_mb:
                                    self.peak_mb = rss_mb
                                break
                except Exception:
                    pass
                self._stop.wait(self.interval)


# ============================================================
# RAG Benchmark
# ============================================================
def benchmark_rag() -> dict:
    """测试 RAG 建库时间、检索时间、命中率。"""
    results: dict = {
        "index_build_time_sec": 0.0,
        "search_times_ms": [],
        "avg_search_time_ms": 0.0,
        "top1_hits": 0,
        "top3_hits": 0,
        "top1_hit_rate": 0.0,
        "top3_hit_rate": 0.0,
        "total_questions": len(TEST_QUESTIONS),
    }

    rag = get_rag_service()

    # 重置 RAG 以便测量建库时间
    rag.initialized = False
    rag.index = None
    rag.chunks = []
    rag.model = None

    monitor = MemoryMonitor()
    monitor.start()

    # 建库时间
    t0 = time.perf_counter()
    rag.initialize()
    t1 = time.perf_counter()
    results["index_build_time_sec"] = round(t1 - t0, 3)

    peak_mb = monitor.stop()
    results["peak_memory_mb"] = round(peak_mb, 1)

    if rag.index is None:
        print("  [警告] RAG 索引为空（rag/ 目录无文档），跳过检索测试")
        return results

    results["index_chunk_count"] = len(rag.chunks)

    # 检索性能
    for i, q in enumerate(TEST_QUESTIONS):
        ts = time.perf_counter()
        hits = rag.search(q, top_k=3)
        te = time.perf_counter()
        elapsed_ms = round((te - ts) * 1000, 2)
        results["search_times_ms"].append(elapsed_ms)

        # 命中率检查
        keywords = RELEVANCE_KEYWORDS.get(i, [])
        if keywords and hits:
            top1_text = (hits[0].get("title", "") + hits[0].get("content", "")).lower()
            if any(kw in top1_text for kw in keywords):
                results["top1_hits"] += 1

            all_text = "".join(
                (h.get("title", "") + h.get("content", "")) for h in hits
            ).lower()
            if any(kw in all_text for kw in keywords):
                results["top3_hits"] += 1

    if results["search_times_ms"]:
        results["avg_search_time_ms"] = round(
            sum(results["search_times_ms"]) / len(results["search_times_ms"]), 2
        )
    results["top1_hit_rate"] = round(results["top1_hits"] / results["total_questions"], 2)
    results["top3_hit_rate"] = round(results["top3_hits"] / results["total_questions"], 2)

    return results


# ============================================================
# AI 问诊 Benchmark
# ============================================================
def benchmark_chat() -> dict:
    """测试流式问诊的 TTFT、Tokens/sec、总耗时等。"""
    results: dict = {
        "cloud_configured": cloud_configured(),
        "questions": [],
        "avg_ttft_ms": 0.0,
        "avg_tokens_per_sec": 0.0,
        "avg_total_time_sec": 0.0,
        "avg_prompt_len": 0,
        "avg_answer_len": 0,
    }

    if not cloud_configured():
        results["error"] = "未配置云端 LLM (DASHSCOPE_API_KEY)，跳过问诊性能测试"
        return results

    db = SessionLocal()
    try:
        # 确保有测试用户
        user = db.query(models.User).first()
        if not user:
            user = models.User(name="Benchmark测试用户", age=65, gender="男", chronic_diseases="高血压,糖尿病")
            db.add(user)
            db.commit()
            db.refresh(user)

        user_id = user.id

        for q in TEST_QUESTIONS:
            # 每个问题创建新会话
            session = create_chat_session(db, user_id)
            session_id = session.id

            q_result: dict = {
                "question": q,
                "ttft_ms": 0.0,
                "total_time_sec": 0.0,
                "tokens": 0,
                "tokens_per_sec": 0.0,
                "prompt_len": 0,
                "answer_len": 0,
                "source": "",
                "error": None,
            }

            try:
                t_start = time.perf_counter()
                first_delta_time: float | None = None
                token_count = 0
                answer_text = ""
                prompt_text = ""

                gen = stream_answer_question(db, session_id, user_id, q, speak=False)
                for event in gen:
                    etype = event.get("type", "")
                    if etype == "meta":
                        # meta 事件中无 prompt 直接信息，忽略
                        pass
                    elif etype == "delta":
                        if first_delta_time is None:
                            first_delta_time = time.perf_counter()
                        text = event.get("text", "")
                        token_count += len(text)  # 以字符数近似 token
                        answer_text += text
                    elif etype == "done":
                        answer_text = event.get("answer", answer_text)
                        q_result["source"] = event.get("source", "")

                t_end = time.perf_counter()

                total_sec = t_end - t_start
                q_result["total_time_sec"] = round(total_sec, 3)
                q_result["tokens"] = token_count
                q_result["answer_len"] = len(answer_text)

                if first_delta_time is not None:
                    q_result["ttft_ms"] = round((first_delta_time - t_start) * 1000, 1)
                    gen_time = t_end - first_delta_time
                    if gen_time > 0 and token_count > 0:
                        q_result["tokens_per_sec"] = round(token_count / gen_time, 1)

            except Exception as exc:
                q_result["error"] = str(exc)

            results["questions"].append(q_result)

        # 计算平均值
        valid = [r for r in results["questions"] if r["error"] is None]
        if valid:
            results["avg_ttft_ms"] = round(
                sum(r["ttft_ms"] for r in valid) / len(valid), 1
            )
            results["avg_tokens_per_sec"] = round(
                sum(r["tokens_per_sec"] for r in valid) / len(valid), 1
            )
            results["avg_total_time_sec"] = round(
                sum(r["total_time_sec"] for r in valid) / len(valid), 3
            )
            results["avg_answer_len"] = round(
                sum(r["answer_len"] for r in valid) / len(valid)
            )

    finally:
        db.close()

    return results


# ============================================================
# 格式化输出
# ============================================================
def format_markdown(rag_results: dict, chat_results: dict) -> str:
    """将 benchmark 结果格式化为 Markdown 表格。"""
    lines: list[str] = []
    lines.append("# AI 问诊 + RAG 性能 Benchmark 报告\n")
    lines.append(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # RAG 结果
    lines.append("## RAG 检索性能\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 建库时间 | {rag_results['index_build_time_sec']} 秒 |")
    lines.append(f"| 索引文档块数 | {rag_results.get('index_chunk_count', 'N/A')} |")
    lines.append(f"| 平均检索时间 | {rag_results['avg_search_time_ms']} ms |")
    lines.append(f"| Top1 命中率 | {rag_results['top1_hit_rate'] * 100:.0f}% ({rag_results['top1_hits']}/{rag_results['total_questions']}) |")
    lines.append(f"| Top3 命中率 | {rag_results['top3_hit_rate'] * 100:.0f}% ({rag_results['top3_hits']}/{rag_results['total_questions']}) |")
    lines.append(f"| 峰值内存 | {rag_results.get('peak_memory_mb', 'N/A')} MB |")
    lines.append("")

    # 各问题检索耗时
    lines.append("### 各问题检索耗时\n")
    lines.append("| # | 问题 | 耗时(ms) |")
    lines.append("|---|------|----------|")
    for i, q in enumerate(TEST_QUESTIONS):
        t = rag_results["search_times_ms"][i] if i < len(rag_results["search_times_ms"]) else "N/A"
        lines.append(f"| {i+1} | {q[:20]}... | {t} |")
    lines.append("")

    # Chat 结果
    lines.append("## AI 问诊性能\n")
    if chat_results.get("error"):
        lines.append(f"⚠️ {chat_results['error']}\n")
    else:
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 平均 TTFT | {chat_results['avg_ttft_ms']} ms |")
        lines.append(f"| 平均 Tokens/sec | {chat_results['avg_tokens_per_sec']} 字符/秒 |")
        lines.append(f"| 平均总耗时 | {chat_results['avg_total_time_sec']} 秒 |")
        lines.append(f"| 平均回复长度 | {chat_results['avg_answer_len']} 字符 |")
        lines.append(f"| LLM 来源 | {chat_results['questions'][0].get('source', 'N/A') if chat_results['questions'] else 'N/A'} |")
        lines.append("")

        # 各问题详细结果
        lines.append("### 各问题详情\n")
        lines.append("| # | 问题 | TTFT(ms) | Tokens/s | 总耗时(s) | 回复长度 | 状态 |")
        lines.append("|---|------|----------|----------|-----------|----------|------|")
        for i, r in enumerate(chat_results["questions"]):
            status = "✅" if r["error"] is None else f"❌ {r['error'][:20]}"
            lines.append(
                f"| {i+1} | {r['question'][:15]}... | {r['ttft_ms']} | "
                f"{r['tokens_per_sec']} | {r['total_time_sec']} | "
                f"{r['answer_len']} | {status} |"
            )
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================
def main() -> dict:
    """运行全部 benchmark，返回结果 dict，同时打印 Markdown 报告。"""
    print("=" * 60)
    print("  AI 问诊 + RAG 性能 Benchmark")
    print("=" * 60)
    print()

    # RAG benchmark
    print("[1/2] RAG 检索性能测试...")
    rag_results = benchmark_rag()
    print(f"  建库时间: {rag_results['index_build_time_sec']}s")
    print(f"  平均检索: {rag_results['avg_search_time_ms']}ms")
    print(f"  Top1/Top3 命中: {rag_results['top1_hit_rate']*100:.0f}%/{rag_results['top3_hit_rate']*100:.0f}%")
    print()

    # Chat benchmark
    print("[2/2] AI 问诊性能测试...")
    chat_results = benchmark_chat()
    if chat_results.get("error"):
        print(f"  ⚠️ {chat_results['error']}")
    else:
        print(f"  平均 TTFT: {chat_results['avg_ttft_ms']}ms")
        print(f"  平均 Tokens/sec: {chat_results['avg_tokens_per_sec']} 字符/秒")
        print(f"  平均总耗时: {chat_results['avg_total_time_sec']}s")
    print()

    # 输出 Markdown 报告
    report = format_markdown(rag_results, chat_results)
    print(report)

    return {
        "rag": rag_results,
        "chat": chat_results,
    }


if __name__ == "__main__":
    main()
