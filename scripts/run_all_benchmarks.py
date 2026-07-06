#!/usr/bin/env python3
"""
汇总 Benchmark 脚本 — 按顺序运行所有 benchmark 测试并生成完整的 Markdown 报告。

用法:
  python scripts/run_all_benchmarks.py
  python scripts/run_all_benchmarks.py --skip-api
  python scripts/run_all_benchmarks.py --skip-cloud
  python scripts/run_all_benchmarks.py --only pipeline
"""

from __future__ import annotations

import argparse
import os
import sys

# 提示: 请使用项目虚拟环境运行此脚本
# .venv/bin/python3 scripts/run_all_benchmarks.py

import time
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

# 项目路径设置，确保能导入同目录下的 benchmark 模块和 backend
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_PROJECT_ROOT))

# 报告输出路径
_REPORT_PATH = _PROJECT_ROOT / "benchmark_report.md"

# 所有 benchmark 模块名称及导入顺序
_BENCHMARK_MODULES = [
    "benchmark_system",
    "benchmark_kws",
    "benchmark_asr",
    "benchmark_chat",
    "benchmark_tts",
    "benchmark_pipeline",
    "benchmark_api",
]


# ============================================================
# 后台系统资源监控线程
# ============================================================
class _BackgroundMonitor:
    """在所有 benchmark 运行期间，后台持续采样 CPU/内存/温度。"""

    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._samples: Dict[str, list] = {
            "cpu_overall": [],
            "mem_used_mb": [],
            "temperatures": [],
        }

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> Dict[str, Any]:
        """停止监控，返回采样统计。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        return self._summarize()

    def _run(self):
        try:
            import benchmark_system
        except ImportError:
            return

        while not self._stop_event.is_set():
            try:
                # CPU 采样（短间隔）
                cpu = benchmark_system.get_cpu_usage(interval=min(0.3, self._interval * 0.3))
                self._samples["cpu_overall"].append(cpu.get("cpu", 0))

                mem = benchmark_system.get_memory_info()
                self._samples["mem_used_mb"].append(mem.get("used_mb", 0))

                temps = benchmark_system.get_temperatures()
                valid_temps = [t["temp_c"] for t in temps if t.get("temp_c") is not None]
                max_temp = max(valid_temps) if valid_temps else 0
                self._samples["temperatures"].append(max_temp)
            except Exception:
                pass

            self._stop_event.wait(self._interval)

    def _summarize(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        for key, values in self._samples.items():
            if not values:
                stats[key] = {"avg": 0, "min": 0, "max": 0}
                continue
            stats[key] = {
                "avg": round(sum(values) / len(values), 1),
                "min": round(min(values), 1),
                "max": round(max(values), 1),
            }
        stats["sample_count"] = max(len(v) for v in self._samples.values()) if self._samples else 0
        return stats


# ============================================================
# 安全提取辅助函数
# ============================================================
def _safe_get(d: Any, *keys: str, default: Any = "N/A") -> Any:
    """从嵌套 dict 中安全提取值，缺失返回 default。"""
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, default)
        else:
            return default
    return current if current is not None else default


def _fmt_ms(val: Any) -> str:
    """将毫秒数值格式化为字符串。"""
    if val is None or val == "N/A":
        return "N/A"
    try:
        return f"{float(val):.1f}ms"
    except (ValueError, TypeError):
        return str(val)


def _fmt_pct(val: Any) -> str:
    """将百分比数值格式化为字符串。"""
    if val is None or val == "N/A":
        return "N/A"
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return str(val)


# ============================================================
# 运行单个 benchmark
# ============================================================
def _run_single(name: str) -> Dict[str, Any]:
    """运行单个 benchmark 模块的 main() 函数，返回其结果 dict。"""
    t0 = time.monotonic()
    print(f"\n{'=' * 60}")
    print(f"  开始运行: {name}")
    print(f"{'=' * 60}")

    try:
        mod = __import__(name)
        result = mod.main()
        elapsed = time.monotonic() - t0
        print(f"\n  ✓ {name} 完成，耗时 {elapsed:.1f}s")
        return {"status": "ok", "result": result, "elapsed_s": round(elapsed, 1)}
    except SystemExit:
        # argparse 可能调用 sys.exit，捕获并忽略
        elapsed = time.monotonic() - t0
        print(f"\n  ⚠ {name} 退出 (SystemExit)，耗时 {elapsed:.1f}s")
        return {"status": "exit", "result": {}, "elapsed_s": round(elapsed, 1)}
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n  ✗ {name} 失败: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e), "result": {}, "elapsed_s": round(elapsed, 1)}


# ============================================================
# 生成 Markdown 报告
# ============================================================
def _generate_report(all_results: Dict[str, Dict], bg_stats: Dict[str, Any]) -> str:
    """根据所有 benchmark 结果和后台监控数据生成完整 Markdown 报告。"""
    lines: list[str] = []
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # ── 标题 ──
    lines.append("# AI Personal Doctor — 边缘 AI 性能测试报告")
    lines.append("")
    lines.append(f"> 测试平台: RK3588  ")
    lines.append(f"> 测试时间: {now_str}  ")
    lines.append("> 项目: AI 私人医生")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 1. 测试环境 ──
    lines.append("## 1. 测试环境")
    lines.append("")
    sys_res = _safe_get(all_results, "benchmark_system", "result", default={})
    snap = _safe_get(sys_res, "snapshot", default={})
    mem = _safe_get(snap, "memory", default={})
    load = _safe_get(snap, "load", default={})
    cpu_usage = _safe_get(snap, "cpu_usage", default={})
    # 统计 CPU 核心数（排除 "cpu" 总项）
    cpu_cores = len([k for k in (cpu_usage if isinstance(cpu_usage, dict) else {}) if k != "cpu"])
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 平台 | RK3588 |")
    lines.append(f"| CPU 核心数 | {cpu_cores if cpu_cores else 'N/A'} |")
    lines.append(f"| 总内存 | {_safe_get(mem, 'total_mb')} MB |")
    lines.append(f"| 可用内存 | {_safe_get(mem, 'available_mb')} MB |")
    lines.append(f"| Swap | {_safe_get(mem, 'swap_total_mb')} MB |")
    lines.append(f"| 系统负载 (1/5/15min) | {_safe_get(load, 'load_1min')} / {_safe_get(load, 'load_5min')} / {_safe_get(load, 'load_15min')} |")
    # 温度
    temps = _safe_get(snap, "temperature", default=[])
    if isinstance(temps, list) and temps:
        valid_temps = [t["temp_c"] for t in temps if isinstance(t, dict) and t.get("temp_c") is not None]
        if valid_temps:
            lines.append(f"| 系统温度 | {max(valid_temps)}°C (最高) |")
    lines.append(f"| 测试时间 | {now_str} |")
    lines.append("")

    # ── 2. KWS 唤醒词检测 ──
    lines.append("## 2. KWS 唤醒词检测")
    lines.append("")
    kws_data = _safe_get(all_results, "benchmark_kws", default={})
    kws_res = _safe_get(kws_data, "result", default={})
    if kws_data.get("status") == "ok" and kws_res:
        acc = _safe_get(kws_res, "accuracy", default={})
        lat = _safe_get(kws_res, "latency", default={})
        cpu_info = _safe_get(kws_res, "cpu", default={})
        mem_info = _safe_get(kws_res, "memory", default={})
        fa = _safe_get(kws_res, "false_alarm", default={})
        mr = _safe_get(kws_res, "miss_rate", default={})
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 唤醒准确率 | {_safe_get(acc, 'hit_rate_pct', default='N/A')}% |")
        lines.append(f"| 平均唤醒延迟 | {_fmt_ms(_safe_get(lat, 'avg_detection_latency_ms'))} |")
        lines.append(f"| CPU 占用 | {_fmt_pct(_safe_get(cpu_info, 'avg_cpu_percent'))} |")
        lines.append(f"| 峰值内存 (RSS) | {_safe_get(mem_info, 'avg_peak_rss_mb', default='N/A')} MB |")
        lines.append(f"| 误唤醒率 | {_safe_get(fa, 'false_alarm_rate_pct', default='N/A')}% |")
        lines.append(f"| 漏唤醒率 | {_safe_get(mr, 'miss_rate_pct', default='N/A')}% |")
    else:
        lines.append(f"> 测试未完成: {_safe_get(kws_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 3. ASR 语音识别 ──
    lines.append("## 3. ASR 语音识别")
    lines.append("")
    asr_data = _safe_get(all_results, "benchmark_asr", default={})
    asr_res = _safe_get(asr_data, "result", default={})
    if asr_data.get("status") == "ok" and asr_res:
        files = _safe_get(asr_res, "files", default=[])
        load_info = _safe_get(asr_res, "model_load", default={})
        if isinstance(load_info, dict) and load_info.get("load_time_ms", -1) > 0:
            lines.append(f"**模型加载时间**: {load_info['load_time_ms']:.2f} ms")
            lines.append("")
        if isinstance(files, list) and files:
            lines.append("| 音频文件 | 时长(ms) | 平均耗时(ms) | RTF | CER | 识别文本 |")
            lines.append("|---------|---------|-------------|-----|-----|---------|")
            for f in files:
                if isinstance(f, dict) and "error" not in f:
                    cer_str = f"{f['cer']:.2%}" if f.get("cer") is not None else "N/A"
                    text_short = f.get("last_text", "")[:20]
                    if len(f.get("last_text", "")) > 20:
                        text_short += "..."
                    lines.append(
                        f"| {f.get('file', 'N/A')} "
                        f"| {f.get('duration_ms', 'N/A')} "
                        f"| {f.get('avg_ms', 'N/A')} "
                        f"| {f.get('rtf', 'N/A')} "
                        f"| {cer_str} "
                        f"| {text_short} |"
                    )
                elif isinstance(f, dict):
                    lines.append(f"| {f.get('file', 'N/A')} | - | 错误: {f.get('error', '')} | - | - | - |")
        else:
            lines.append("> 无测试结果")
    else:
        lines.append(f"> 测试未完成: {_safe_get(asr_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 4. RAG 知识检索 ──
    lines.append("## 4. RAG 知识检索")
    lines.append("")
    chat_data = _safe_get(all_results, "benchmark_chat", default={})
    chat_res = _safe_get(chat_data, "result", default={})
    rag_res = _safe_get(chat_res, "rag", default={})
    if chat_data.get("status") == "ok" and rag_res:
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 建库时间 | {_safe_get(rag_res, 'index_build_time_sec')} 秒 |")
        lines.append(f"| 索引文档块数 | {_safe_get(rag_res, 'index_chunk_count')} |")
        lines.append(f"| 平均检索时间 | {_safe_get(rag_res, 'avg_search_time_ms')} ms |")
        top1 = _safe_get(rag_res, "top1_hit_rate", default=0)
        top3 = _safe_get(rag_res, "top3_hit_rate", default=0)
        try:
            lines.append(f"| Top1 命中率 | {float(top1) * 100:.0f}% |")
            lines.append(f"| Top3 命中率 | {float(top3) * 100:.0f}% |")
        except (ValueError, TypeError):
            lines.append(f"| Top1 命中率 | {top1} |")
            lines.append(f"| Top3 命中率 | {top3} |")
        lines.append(f"| 峰值内存 | {_safe_get(rag_res, 'peak_memory_mb')} MB |")
    else:
        lines.append(f"> 测试未完成: {_safe_get(chat_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 5. AI 问诊 (LLM) ──
    lines.append("## 5. AI 问诊 (LLM)")
    lines.append("")
    llm_res = _safe_get(chat_res, "chat", default={})
    if chat_data.get("status") == "ok" and llm_res:
        if llm_res.get("error"):
            lines.append(f"> {llm_res['error']}")
        else:
            lines.append("| 指标 | 值 |")
            lines.append("|------|-----|")
            lines.append(f"| 平均 TTFT | {_safe_get(llm_res, 'avg_ttft_ms')} ms |")
            lines.append(f"| 平均 Tokens/sec | {_safe_get(llm_res, 'avg_tokens_per_sec')} 字符/秒 |")
            lines.append(f"| 平均总耗时 | {_safe_get(llm_res, 'avg_total_time_sec')} 秒 |")
            lines.append(f"| 平均回复长度 | {_safe_get(llm_res, 'avg_answer_len')} 字符 |")
    else:
        lines.append(f"> 测试未完成: {_safe_get(chat_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 6. TTS 语音合成 ──
    lines.append("## 6. TTS 语音合成")
    lines.append("")
    tts_data = _safe_get(all_results, "benchmark_tts", default={})
    tts_res = _safe_get(tts_data, "result", default={})
    if tts_data.get("status") == "ok" and tts_res:
        # 云端 TTS
        cloud_tts = _safe_get(tts_res, "cloud_tts", default={})
        lines.append("### 云端 TTS (CosyVoice)")
        lines.append("")
        if cloud_tts.get("skipped"):
            lines.append(f"> 已跳过: {cloud_tts.get('reason', 'N/A')}")
        else:
            lines.append("| 指标 | 值 |")
            lines.append("|------|-----|")
            lines.append(f"| 引擎 | {_safe_get(cloud_tts, 'engine')} |")
            lines.append(f"| 平均合成耗时 | {_safe_get(cloud_tts, 'avg_synth_time_s')} 秒 |")
            lines.append(f"| 平均 RTF | {_safe_get(cloud_tts, 'avg_rtf')} |")
        lines.append("")

        # 本地 TTS
        piper_tts = _safe_get(tts_res, "piper_tts", default={})
        lines.append("### 本地 TTS (Piper)")
        lines.append("")
        if piper_tts.get("skipped"):
            lines.append(f"> 已跳过: {piper_tts.get('reason', 'N/A')}")
        else:
            lines.append("| 指标 | 值 |")
            lines.append("|------|-----|")
            lines.append(f"| 引擎 | {_safe_get(piper_tts, 'engine')} |")
            lines.append(f"| 平均合成耗时 | {_safe_get(piper_tts, 'avg_synth_time_s')} 秒 |")
            lines.append(f"| 平均 RTF | {_safe_get(piper_tts, 'avg_rtf')} |")
            lines.append(f"| 峰值内存 | {_safe_get(piper_tts, 'peak_rss_mb')} MB |")
    else:
        lines.append(f"> 测试未完成: {_safe_get(tts_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 7. 全链路性能 ──
    lines.append("## 7. 全链路性能")
    lines.append("")
    pipe_data = _safe_get(all_results, "benchmark_pipeline", default={})
    pipe_res = _safe_get(pipe_data, "result", default={})
    pipe_summary = _safe_get(pipe_res, "summary", default={})
    if pipe_data.get("status") == "ok" and pipe_summary:
        lines.append("| 步骤 | 平均耗时(ms) | 最小(ms) | 最大(ms) |")
        lines.append("|------|-------------|---------|---------|")
        step_labels = {
            "kws": "KWS 唤醒",
            "asr": "ASR 识别",
            "rag": "RAG 检索",
            "llm": "LLM 生成",
            "tts": "TTS 合成",
            "total": "**总计**",
        }
        for key in ("kws", "asr", "rag", "llm", "tts", "total"):
            s = _safe_get(pipe_summary, key, default=None)
            if s is None or not isinstance(s, dict):
                continue
            label = step_labels.get(key, key)
            lines.append(f"| {label} | {_safe_get(s, 'avg_ms')} | {_safe_get(s, 'min_ms')} | {_safe_get(s, 'max_ms')} |")
    else:
        lines.append(f"> 测试未完成: {_safe_get(pipe_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 8. API 响应速度 ──
    lines.append("## 8. API 响应速度")
    lines.append("")
    api_data = _safe_get(all_results, "benchmark_api", default={})
    api_res = _safe_get(api_data, "result", default={})
    if api_data.get("status") == "ok" and api_res:
        api_tests = _safe_get(api_res, "tests", default=[])
        if api_res.get("error"):
            lines.append(f"> {api_res['error']}")
        elif isinstance(api_tests, list) and api_tests:
            lines.append("| API | 描述 | 平均(ms) | 最小(ms) | 最大(ms) | 成功率 |")
            lines.append("|-----|------|---------|---------|---------|--------|")
            for r in api_tests:
                if isinstance(r, dict):
                    api_name = f"`{r.get('method', '')} {r.get('path', '')}`"
                    lines.append(
                        f"| {api_name} | {r.get('description', '')} "
                        f"| {r.get('avg_ms', 'N/A')} "
                        f"| {r.get('min_ms', 'N/A')} "
                        f"| {r.get('max_ms', 'N/A')} "
                        f"| {r.get('success_rate', 'N/A')}% |"
                    )
            overall_avg_api = _safe_get(api_res, "overall_avg_ms", default="N/A")
            lines.append("")
            lines.append(f"**所有 API 平均响应时间: {overall_avg_api}ms**")
        else:
            lines.append("> 无测试结果")
    else:
        lines.append(f"> 测试未完成: {_safe_get(api_data, 'error', default='跳过或失败')}")
    lines.append("")

    # ── 9. 系统资源（后台监控） ──
    lines.append("## 9. 系统资源")
    lines.append("")
    lines.append("*以下为所有 benchmark 运行期间后台持续采样的系统资源数据。*")
    lines.append("")
    lines.append("| 指标 | 平均值 | 峰值 |")
    lines.append("|------|--------|------|")
    cpu_stats = _safe_get(bg_stats, "cpu_overall", default={})
    mem_stats = _safe_get(bg_stats, "mem_used_mb", default={})
    temp_stats = _safe_get(bg_stats, "temperatures", default={})
    lines.append(f"| CPU 使用率 | {_safe_get(cpu_stats, 'avg')}% | {_safe_get(cpu_stats, 'max')}% |")
    lines.append(f"| 已用内存 | {_safe_get(mem_stats, 'avg')} MB | {_safe_get(mem_stats, 'max')} MB |")
    lines.append(f"| 系统温度 | {_safe_get(temp_stats, 'avg')}°C | {_safe_get(temp_stats, 'max')}°C |")
    lines.append(f"| 采样次数 | {_safe_get(bg_stats, 'sample_count', default=0)} |  |")
    lines.append("")

    # ── 分隔线 ──
    lines.append("---")
    lines.append("")

    # ── Performance Summary（最重要，适合贴 PPT） ──
    lines.append("## AI Personal Doctor Performance Summary")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")

    # 系统平均响应时间（API）
    api_overall = _safe_get(api_res, "overall_avg_ms", default="N/A")
    lines.append(f"| 系统平均响应时间 | {_fmt_ms(api_overall)} |")

    # KWS 唤醒延迟
    kws_latency = _safe_get(kws_res, "latency", "avg_detection_latency_ms", default="N/A")
    lines.append(f"| KWS 唤醒延迟 | {_fmt_ms(kws_latency)} |")

    # ASR 识别耗时 — 取所有文件平均
    asr_avg_ms = "N/A"
    asr_files = _safe_get(asr_res, "files", default=[])
    if isinstance(asr_files, list) and asr_files:
        valid_asr = [f["avg_ms"] for f in asr_files if isinstance(f, dict) and "avg_ms" in f]
        if valid_asr:
            asr_avg_ms = round(sum(valid_asr) / len(valid_asr), 1)
    lines.append(f"| ASR 识别耗时 | {_fmt_ms(asr_avg_ms)} |")

    # RAG 检索耗时
    rag_avg = _safe_get(rag_res, "avg_search_time_ms", default="N/A")
    lines.append(f"| RAG 检索耗时 | {_fmt_ms(rag_avg)} |")

    # LLM 问诊耗时（秒 -> 毫秒）
    llm_total_sec = _safe_get(llm_res, "avg_total_time_sec", default="N/A")
    if llm_total_sec != "N/A":
        try:
            llm_ms = round(float(llm_total_sec) * 1000, 1)
            lines.append(f"| LLM 问诊耗时 | {_fmt_ms(llm_ms)} |")
        except (ValueError, TypeError):
            lines.append(f"| LLM 问诊耗时 | N/A |")
    else:
        lines.append(f"| LLM 问诊耗时 | N/A |")

    # TTS 合成耗时 — 取 Piper（本地）优先，否则取云端，单位秒->毫秒
    tts_avg = "N/A"
    piper_tts = _safe_get(tts_res, "piper_tts", default={})
    cloud_tts = _safe_get(tts_res, "cloud_tts", default={})
    if isinstance(piper_tts, dict) and not piper_tts.get("skipped") and piper_tts.get("avg_synth_time_s") is not None:
        try:
            tts_avg = round(float(piper_tts["avg_synth_time_s"]) * 1000, 1)
        except (ValueError, TypeError):
            pass
    elif isinstance(cloud_tts, dict) and not cloud_tts.get("skipped") and cloud_tts.get("avg_synth_time_s") is not None:
        try:
            tts_avg = round(float(cloud_tts["avg_synth_time_s"]) * 1000, 1)
        except (ValueError, TypeError):
            pass
    lines.append(f"| TTS 合成耗时 | {_fmt_ms(tts_avg)} |")

    # 全链路耗时
    pipe_total = _safe_get(pipe_summary, "total", "avg_ms", default="N/A")
    lines.append(f"| 全链路耗时 | {_fmt_ms(pipe_total)} |")

    # ASR RTF
    asr_rtf = "N/A"
    if isinstance(asr_files, list) and asr_files:
        valid_rtf = [f["rtf"] for f in asr_files if isinstance(f, dict) and "rtf" in f]
        if valid_rtf:
            asr_rtf = round(sum(valid_rtf) / len(valid_rtf), 4)
    lines.append(f"| ASR RTF | {asr_rtf} |")

    # TTS RTF
    tts_rtf = "N/A"
    if isinstance(piper_tts, dict) and not piper_tts.get("skipped") and piper_tts.get("avg_rtf") is not None:
        tts_rtf = piper_tts["avg_rtf"]
    elif isinstance(cloud_tts, dict) and not cloud_tts.get("skipped") and cloud_tts.get("avg_rtf") is not None:
        tts_rtf = cloud_tts["avg_rtf"]
    lines.append(f"| TTS RTF | {tts_rtf} |")

    # CPU 峰值占用（后台监控）
    cpu_peak = _safe_get(cpu_stats, "max", default="N/A")
    lines.append(f"| CPU 峰值占用 | {_fmt_pct(cpu_peak)} |")

    # 内存峰值占用
    mem_peak = _safe_get(mem_stats, "max", default="N/A")
    lines.append(f"| 内存峰值占用 | {mem_peak}MB |" if mem_peak != "N/A" else "| 内存峰值占用 | N/A |")

    # 系统温度峰值
    temp_peak = _safe_get(temp_stats, "max", default="N/A")
    lines.append(f"| 系统温度峰值 | {temp_peak}°C |" if temp_peak != "N/A" else "| 系统温度峰值 | N/A |")

    lines.append("")
    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================
def run_all(
    skip_api: bool = False,
    skip_cloud: bool = False,
    only: Optional[str] = None,
) -> Dict[str, Any]:
    """
    按顺序运行所有 benchmark 测试并生成 Markdown 报告。

    Args:
        skip_api: 跳过 API 测试（需要后端运行）
        skip_cloud: 跳过需要网络的测试（LLM、云端 TTS）
        only: 只运行指定的 benchmark（如 "pipeline"）

    Returns:
        包含所有 benchmark 结果的 dict
    """
    total_start = time.monotonic()

    print("╔════════════════════════════════════════════════════════╗")
    print("║   AI Personal Doctor — 性能测试汇总                   ║")
    print("╚════════════════════════════════════════════════════════╝")
    print(f"  测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if skip_api:
        print("  → 跳过 API 测试 (--skip-api)")
    if skip_cloud:
        print("  → 跳过云端测试 (--skip-cloud)")
    if only:
        print(f"  → 仅运行: {only}")
    print()

    # 确定要运行的模块列表
    if only:
        # 支持 "pipeline" 或 "benchmark_pipeline" 两种写法
        target = only if only.startswith("benchmark_") else f"benchmark_{only}"
        if target not in _BENCHMARK_MODULES:
            print(f"  ✗ 未知的 benchmark: {only}")
            print(f"  可选: {', '.join(m.replace('benchmark_', '') for m in _BENCHMARK_MODULES)}")
            return {}
        modules_to_run = [target]
    else:
        modules_to_run = list(_BENCHMARK_MODULES)

    # 根据 --skip-api / --skip-cloud 过滤
    if skip_api and "benchmark_api" in modules_to_run:
        modules_to_run.remove("benchmark_api")
    if skip_cloud:
        # benchmark_chat（包含 LLM）和 benchmark_tts（包含云端 TTS）仍然运行，
        # 但在它们内部会检测到 API key 缺失而自动跳过云端部分。
        # 这里设置环境变量让它们知道要跳过云端
        os.environ["SKIP_CLOUD_BENCHMARKS"] = "1"

    # 启动后台系统资源监控线程
    bg_monitor = _BackgroundMonitor(interval=2.0)
    bg_monitor.start()
    print("  ▶ 后台系统资源监控已启动")

    # 顺序运行各 benchmark
    all_results: Dict[str, Dict] = {}
    for i, mod_name in enumerate(modules_to_run):
        short_name = mod_name.replace("benchmark_", "")
        print(f"\n{'━' * 60}")
        print(f"  [{i + 1}/{len(modules_to_run)}] {short_name.upper()}")
        print(f"{'━' * 60}")

        # 对于 benchmark_system 和 benchmark_api，它们使用 argparse，
        # 需要临时清理 sys.argv 避免参数冲突
        original_argv = sys.argv
        sys.argv = [mod_name + ".py"]

        try:
            result = _run_single(mod_name)
        finally:
            sys.argv = original_argv

        all_results[mod_name] = result

    # 停止后台监控
    bg_stats = bg_monitor.stop()
    print("\n  ■ 后台系统资源监控已停止")

    total_elapsed = time.monotonic() - total_start
    print(f"\n  总耗时: {total_elapsed:.1f}s")

    # 生成 Markdown 报告
    print(f"\n{'━' * 60}")
    print("  生成 Markdown 报告...")

    report = _generate_report(all_results, bg_stats)

    # 写入文件
    report_path = str(_REPORT_PATH)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  ✓ 报告已保存到: {report_path}")

    # 也在终端打印报告
    print(f"\n{'━' * 60}")
    print(report)

    # 返回所有结果
    return {
        "benchmarks": all_results,
        "bg_monitor": bg_stats,
        "report_path": report_path,
        "total_elapsed_s": round(total_elapsed, 1),
    }


# ============================================================
# 命令行入口
# ============================================================
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Personal Doctor — 汇总运行所有 benchmark 测试并生成 Markdown 报告"
    )
    parser.add_argument(
        "--skip-api", action="store_true",
        help="跳过 API 测试（需要后端运行）",
    )
    parser.add_argument(
        "--skip-cloud", action="store_true",
        help="跳过需要网络的测试（LLM、云端 TTS）",
    )
    parser.add_argument(
        "--only", type=str, default=None,
        help="只运行指定的 benchmark（如 pipeline, kws, asr, chat, tts, system, api）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_all(
        skip_api=args.skip_api,
        skip_cloud=args.skip_cloud,
        only=args.only,
    )
