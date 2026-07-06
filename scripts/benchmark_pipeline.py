#!/usr/bin/env python3
"""
全链路性能测试 — AI 医生问诊链路基准测试

模拟完整链路并分步计时:
  用户说话 → KWS 唤醒 → ASR 识别 → RAG 检索 → LLM 生成 → TTS 合成 → 总耗时

用法:
  python scripts/benchmark_pipeline.py
"""

import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── 测试场景 ──────────────────────────────────────────────
PIPELINE_SCENARIOS = [
    "我最近头晕三天了，有高血压，怎么办？",
    "感冒发烧38.5度，可以吃什么药？",
    "糖尿病患者饮食要注意什么？",
]

# ── KWS 相关路径 ──────────────────────────────────────────
SHERPA_BIN = "/home/elf/Qwen_test/sherpa/bin/sherpa-onnx-keyword-spotter"
SHERPA_LIB = "/home/elf/Qwen_test/sherpa/lib"
KWS_DIR = "/home/elf/Qwen_test/sherpa/kws"
KWS_TEST_WAV = os.path.join(KWS_DIR, "test_wavs", "0.wav")

# ── ASR 测试音频 ──────────────────────────────────────────
ASR_TEST_WAV = "/home/elf/Qwen_test/sherpa/asr_sensevoice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs/zh.wav"


def _ms(seconds: float) -> float:
    """秒转毫秒，保留 1 位小数"""
    return round(seconds * 1000, 1)


# ── Step 1: KWS 唤醒检测 ──────────────────────────────────
def bench_kws() -> dict:
    """用 C++ 可执行文件处理测试音频，计时"""
    result = {"name": "KWS", "ms": 0.0, "ok": False, "detail": ""}

    if not os.path.isfile(SHERPA_BIN):
        result["detail"] = f"可执行文件不存在: {SHERPA_BIN}"
        return result
    if not os.path.isfile(KWS_TEST_WAV):
        result["detail"] = f"测试音频不存在: {KWS_TEST_WAV}"
        return result

    encoder = os.path.join(KWS_DIR, "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx")
    decoder = os.path.join(KWS_DIR, "decoder-epoch-12-avg-2-chunk-16-left-64.onnx")
    joiner = os.path.join(KWS_DIR, "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx")
    tokens = os.path.join(KWS_DIR, "tokens.txt")
    keywords = os.path.join(KWS_DIR, "test_wavs", "test_keywords.txt")

    for f in (encoder, decoder, joiner, tokens):
        if not os.path.isfile(f):
            result["detail"] = f"模型文件缺失: {f}"
            return result

    # 如果 keywords 文件不存在，使用 kws 目录下的 keywords.txt
    if not os.path.isfile(keywords):
        keywords = os.path.join(KWS_DIR, "keywords.txt")
        if not os.path.isfile(keywords):
            result["detail"] = "keywords 文件不存在"
            return result

    cmd = [
        SHERPA_BIN,
        f"--encoder={encoder}",
        f"--decoder={decoder}",
        f"--joiner={joiner}",
        f"--tokens={tokens}",
        f"--keywords-file={keywords}",
        "--num-threads=2",
        KWS_TEST_WAV,
    ]
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = SHERPA_LIB + ":" + env.get("LD_LIBRARY_PATH", "")

    try:
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        elapsed = time.perf_counter() - t0
        result["ms"] = _ms(elapsed)
        result["ok"] = True
        result["detail"] = proc.stdout.strip()[:200] if proc.stdout else ""
    except subprocess.TimeoutExpired:
        result["detail"] = "超时 (>30s)"
    except Exception as e:
        result["detail"] = str(e)

    return result


# ── Step 2: ASR 语音识别 ──────────────────────────────────
def bench_asr() -> dict:
    """调用 local_asr.transcribe_wav() 进行语音识别"""
    result = {"name": "ASR", "ms": 0.0, "ok": False, "detail": ""}

    if not os.path.isfile(ASR_TEST_WAV):
        result["detail"] = f"测试音频不存在: {ASR_TEST_WAV}"
        return result

    try:
        from backend.services.local_asr import transcribe_wav
    except Exception as e:
        result["detail"] = f"导入 local_asr 失败: {e}"
        return result

    try:
        t0 = time.perf_counter()
        resp = transcribe_wav(ASR_TEST_WAV)
        elapsed = time.perf_counter() - t0
        result["ms"] = _ms(elapsed)
        result["ok"] = resp.get("ok", False)
        result["detail"] = resp.get("text", "")[:100]
    except Exception as e:
        result["detail"] = f"ASR 异常: {e}"

    return result


# ── Step 3: RAG 知识库检索 ────────────────────────────────
def bench_rag(question: str) -> dict:
    """调用 rag_service.search() 检索医疗知识"""
    result = {"name": "RAG", "ms": 0.0, "ok": False, "detail": ""}

    try:
        from backend.services.rag_service import get_rag_service
    except Exception as e:
        result["detail"] = f"导入 rag_service 失败: {e}"
        return result

    try:
        rag = get_rag_service()
        # initialize 只在首次调用时加载，后续复用
        rag.initialize()

        t0 = time.perf_counter()
        hits = rag.search(question, top_k=3)
        elapsed = time.perf_counter() - t0
        result["ms"] = _ms(elapsed)
        result["ok"] = True
        result["detail"] = f"{len(hits)} 条结果"
    except Exception as e:
        result["detail"] = f"RAG 异常: {e}"

    return result


# ── Step 4: LLM 大模型生成 ────────────────────────────────
def bench_llm(prompt: str) -> dict:
    """调用 cloud_llm_service.stream_chat() 流式生成，记录 TTFT 和总时间"""
    result = {"name": "LLM", "ms": 0.0, "ttft_ms": 0.0, "ok": False, "detail": ""}

    try:
        from backend.services.cloud_llm_service import stream_chat, cloud_configured
    except Exception as e:
        result["detail"] = f"导入 cloud_llm_service 失败: {e}"
        return result

    if not cloud_configured():
        result["detail"] = "云端 LLM 未配置 (DASHSCOPE_API_KEY)"
        return result

    try:
        chunks = []
        ttft = None
        t0 = time.perf_counter()
        for chunk in stream_chat(prompt, speak=False):
            if ttft is None:
                ttft = time.perf_counter() - t0
            chunks.append(chunk)
        elapsed = time.perf_counter() - t0

        result["ms"] = _ms(elapsed)
        result["ttft_ms"] = _ms(ttft) if ttft is not None else 0.0
        result["ok"] = True
        full_text = "".join(chunks)
        result["detail"] = f"{len(full_text)} 字"
    except Exception as e:
        result["detail"] = f"LLM 异常: {e}"

    return result


# ── Step 5: TTS 语音合成 ──────────────────────────────────
def bench_tts(text: str) -> dict:
    """调用 cloud_tts_service.synthesize_bytes() 合成语音"""
    result = {"name": "TTS", "ms": 0.0, "ok": False, "detail": ""}

    try:
        from backend.services.cloud_tts_service import synthesize_bytes, cloud_tts_configured
    except Exception as e:
        result["detail"] = f"导入 cloud_tts_service 失败: {e}"
        return result

    if not cloud_tts_configured():
        result["detail"] = "云端 TTS 未配置 (DASHSCOPE_API_KEY)"
        return result

    # 截取前 80 字作为 TTS 输入，避免过长
    tts_text = text[:80] if len(text) > 80 else text

    try:
        t0 = time.perf_counter()
        audio_bytes = synthesize_bytes(tts_text)
        elapsed = time.perf_counter() - t0
        result["ms"] = _ms(elapsed)
        result["ok"] = True
        result["detail"] = f"{len(audio_bytes)} bytes"
    except Exception as e:
        result["detail"] = f"TTS 异常: {e}"

    return result


# ── 单场景完整链路 ────────────────────────────────────────
def run_pipeline(scenario: str, run_kws: bool = True, run_asr: bool = True) -> dict:
    """
    对单个问诊场景执行完整链路，返回各步骤耗时。

    Args:
        scenario: 医疗问题文本
        run_kws: 是否测试 KWS（仅首次需要）
        run_asr: 是否测试 ASR（仅首次需要）

    Returns:
        dict 包含各步骤结果
    """
    steps = {}

    # KWS 和 ASR 跟具体问题无关，仅测一次即可
    if run_kws:
        steps["kws"] = bench_kws()
    if run_asr:
        steps["asr"] = bench_asr()

    # RAG 检索
    steps["rag"] = bench_rag(scenario)

    # LLM 生成
    steps["llm"] = bench_llm(scenario)

    # TTS 合成 —— 用 LLM 输出的前 80 字做合成测试
    tts_text = "这是一段用于语音合成的测试文本。"
    if steps["llm"]["ok"] and steps["llm"].get("detail"):
        # detail 格式 "N 字"，实际文本在 stream_chat 中已消费
        # 退而使用场景问题本身作为 TTS 输入
        tts_text = scenario
    steps["tts"] = bench_tts(tts_text)

    # 汇总
    total_ms = sum(s.get("ms", 0) for s in steps.values())
    return {
        "scenario": scenario,
        "steps": steps,
        "total_ms": round(total_ms, 1),
    }


# ── 打印单场景结果 ────────────────────────────────────────
def _print_scenario(result: dict) -> None:
    scenario = result["scenario"]
    steps = result["steps"]
    print(f"\n场景: \"{scenario[:30]}{'...' if len(scenario) > 30 else ''}\"")

    for key in ("kws", "asr", "rag", "llm", "tts"):
        if key not in steps:
            continue
        s = steps[key]
        name = s["name"].upper().ljust(6)
        status = "✓" if s.get("ok") else "✗"
        extra = ""
        if key == "llm" and s.get("ttft_ms"):
            extra = f" (TTFT: {s['ttft_ms']:.0f}ms)"
        if not s.get("ok"):
            extra += f" [{s.get('detail', '')}]"
        print(f"  {name} {s['ms']:>8.0f}ms {status}{extra}")

    print(f"  {'Total':6} {result['total_ms']:>8.0f}ms")


# ── 主函数 ────────────────────────────────────────────────
def main() -> dict:
    """
    执行全链路性能测试，返回汇总结果 dict。

    Returns:
        {
            "benchmark": "pipeline",
            "scenarios": [...],
            "summary": {...}
        }
    """
    print("=" * 60)
    print("  全链路性能测试 (Pipeline Benchmark)")
    print("=" * 60)

    results = []
    for i, scenario in enumerate(PIPELINE_SCENARIOS):
        print(f"\n{'─' * 50}")
        print(f"[{i + 1}/{len(PIPELINE_SCENARIOS)}] 测试场景: {scenario[:40]}...")
        # KWS 和 ASR 只在第一个场景测试（它们与具体问题无关）
        r = run_pipeline(scenario, run_kws=(i == 0), run_asr=(i == 0))
        _print_scenario(r)
        results.append(r)

    # ── 汇总统计 ──
    all_steps = {}  # step_name -> list of ms
    for r in results:
        for key, s in r["steps"].items():
            all_steps.setdefault(key, []).append(s.get("ms", 0))

    summary = {}
    for key, ms_list in all_steps.items():
        summary[key] = {
            "avg_ms": round(sum(ms_list) / len(ms_list), 1),
            "min_ms": round(min(ms_list), 1),
            "max_ms": round(max(ms_list), 1),
        }

    totals = [r["total_ms"] for r in results]
    summary["total"] = {
        "avg_ms": round(sum(totals) / len(totals), 1),
        "min_ms": round(min(totals), 1),
        "max_ms": round(max(totals), 1),
    }

    # ── 打印 Markdown 表格 ──
    print(f"\n{'=' * 60}")
    print("  汇总结果 (Markdown)")
    print("=" * 60)
    print()
    print("| 步骤 | 平均耗时(ms) | 最小(ms) | 最大(ms) |")
    print("|------|-------------|---------|---------|")
    step_display = {
        "kws": "KWS 唤醒",
        "asr": "ASR 识别",
        "rag": "RAG 检索",
        "llm": "LLM 生成",
        "tts": "TTS 合成",
        "total": "**总计**",
    }
    for key in ("kws", "asr", "rag", "llm", "tts", "total"):
        if key not in summary:
            continue
        s = summary[key]
        label = step_display.get(key, key)
        print(f"| {label} | {s['avg_ms']:.1f} | {s['min_ms']:.1f} | {s['max_ms']:.1f} |")

    # LLM TTFT 单独列出
    ttfts = []
    for r in results:
        llm = r["steps"].get("llm", {})
        if llm.get("ttft_ms"):
            ttfts.append(llm["ttft_ms"])
    if ttfts:
        avg_ttft = round(sum(ttfts) / len(ttfts), 1)
        print(f"\nLLM 首 Token 延迟 (TTFT): 平均 {avg_ttft}ms")

    print()

    return {
        "benchmark": "pipeline",
        "scenarios": results,
        "summary": summary,
    }


if __name__ == "__main__":
    main()
