#!/usr/bin/env python3
"""
KWS（唤醒词检测）性能 Benchmark 脚本

测试 AI-Personal-Doctor 项目使用的 Sherpa-ONNX KWS 系统，
涵盖唤醒准确率、延迟、CPU/内存占用、误唤醒率、漏唤醒率等指标。
使用 C++ 可执行文件 sherpa-onnx-keyword-spotter 进行测试。
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_kws.py

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 项目路径设置
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ============================================================
# 默认路径配置
# ============================================================
_SHERPA_BIN = os.getenv(
    "SHERPA_KWS_SPOTTER_BIN",
    "/home/elf/Qwen_test/sherpa/bin/sherpa-onnx-keyword-spotter",
)
_SHERPA_LIB_DIR = "/home/elf/Qwen_test/sherpa/lib"

_KWS_DIR = os.getenv("SHERPA_KWS_DIR", "/home/elf/Qwen_test/sherpa/kws")
_KWS_ENCODER = os.path.join(_KWS_DIR, "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx")
_KWS_DECODER = os.path.join(_KWS_DIR, "decoder-epoch-12-avg-2-chunk-16-left-64.onnx")
_KWS_JOINER = os.path.join(_KWS_DIR, "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx")
_KWS_TOKENS = os.path.join(_KWS_DIR, "tokens.txt")

_TEST_WAV_DIR = "/home/elf/Qwen_test/sherpa/kws/test_wavs"
_TEST_KEYWORDS = os.path.join(_TEST_WAV_DIR, "test_keywords.txt")

# 不含唤醒词的音频（用于误唤醒测试）
_FALSE_ALARM_WAV_DIR = (
    "/home/elf/Qwen_test/sherpa/asr_sensevoice"
    "/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs"
)

# 每个音频重复测试次数
_REPEAT = 3
_NUM_THREADS = 2


# ============================================================
# 工具函数
# ============================================================

def _build_env() -> dict:
    """构建子进程环境变量，确保 LD_LIBRARY_PATH 包含 Sherpa 共享库。"""
    env = os.environ.copy()
    ld_path = env.get("LD_LIBRARY_PATH", "")
    if _SHERPA_LIB_DIR not in ld_path:
        env["LD_LIBRARY_PATH"] = f"{_SHERPA_LIB_DIR}:{ld_path}" if ld_path else _SHERPA_LIB_DIR
    return env


def _run_kws(wav_files: List[str], keywords_file: str, timeout: float = 60.0) -> Tuple[str, float]:
    """
    运行 sherpa-onnx-keyword-spotter 并返回 (stdout+stderr 输出, 耗时毫秒)。
    """
    cmd = [
        _SHERPA_BIN,
        f"--encoder={_KWS_ENCODER}",
        f"--decoder={_KWS_DECODER}",
        f"--joiner={_KWS_JOINER}",
        f"--tokens={_KWS_TOKENS}",
        f"--keywords-file={keywords_file}",
        f"--num-threads={_NUM_THREADS}",
    ] + wav_files

    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_build_env(),
        timeout=timeout,
    )
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    output = proc.stdout + proc.stderr
    return output, elapsed_ms


def _parse_detections(output: str) -> List[Dict[str, Any]]:
    """
    解析 sherpa-onnx-keyword-spotter 输出，提取所有关键词检测结果。

    输出格式示例:
        /path/to/5.wav
        {"start_time":0.00, "keyword": "周望军", "timestamps": [...], "tokens":[...]}
    """
    detections: List[Dict[str, Any]] = []
    current_wav = None
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # wav 文件路径行
        if stripped.endswith(".wav"):
            current_wav = stripped
            continue
        # JSON 检测行
        if stripped.startswith("{") and '"keyword"' in stripped:
            try:
                det = json.loads(stripped)
                det["wav_file"] = current_wav or ""
                detections.append(det)
            except json.JSONDecodeError:
                pass
    return detections


def _get_test_wavs() -> List[str]:
    """获取测试音频文件列表（0.wav - 6.wav）。"""
    wavs = sorted(glob.glob(os.path.join(_TEST_WAV_DIR, "*.wav")))
    return wavs


def _get_false_alarm_wavs() -> List[str]:
    """获取不含唤醒词的音频文件列表（用于误唤醒测试）。"""
    wavs = sorted(glob.glob(os.path.join(_FALSE_ALARM_WAV_DIR, "*.wav")))
    return wavs


def _read_peak_rss_kb(pid: int) -> int:
    """从 /proc/<pid>/status 读取当前 VmRSS（KB）。"""
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _monitor_resources(
    cmd: List[str], timeout: float = 60.0
) -> Dict[str, Any]:
    """
    运行命令并监控 CPU 时间和峰值内存。
    返回 {"peak_rss_kb": int, "cpu_user_ms": float, "cpu_sys_ms": float, "wall_ms": float}
    """
    env = _build_env()
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    peak_rss_kb = 0
    poll_interval = 0.02  # 20ms 采样间隔
    while proc.poll() is None:
        rss = _read_peak_rss_kb(proc.pid)
        if rss > peak_rss_kb:
            peak_rss_kb = rss
        time.sleep(poll_interval)

    wall_ms = (time.monotonic() - t0) * 1000.0
    proc.wait(timeout=5)

    # 获取 CPU 时间（用户态 + 内核态）
    cpu_user_ms = 0.0
    cpu_sys_ms = 0.0
    try:
        # /proc/<pid>/stat 在进程退出后不可用，改用 resource 或 rusage
        import resource
        # 子进程的资源使用可以通过 os.wait4 获取，但进程已结束
        # 退而求其次，用 /usr/bin/time 的方式无法追溯
        # 使用 getrusage(RUSAGE_CHILDREN) 的差值
    except Exception:
        pass

    return {
        "peak_rss_kb": peak_rss_kb,
        "peak_rss_mb": round(peak_rss_kb / 1024.0, 1),
        "wall_ms": round(wall_ms, 2),
    }


def _check_prerequisites() -> Optional[str]:
    """检查必要文件是否存在，返回错误信息或 None。"""
    checks = [
        (_SHERPA_BIN, "KWS 可执行文件"),
        (_KWS_ENCODER, "KWS encoder 模型"),
        (_KWS_DECODER, "KWS decoder 模型"),
        (_KWS_JOINER, "KWS joiner 模型"),
        (_KWS_TOKENS, "tokens.txt"),
        (_TEST_KEYWORDS, "测试关键词文件"),
    ]
    missing = []
    for path, name in checks:
        if not os.path.isfile(path):
            missing.append(f"  {name}: {path}")
    if missing:
        return "缺少必要文件:\n" + "\n".join(missing)
    if not _get_test_wavs():
        return f"未找到测试音频: {_TEST_WAV_DIR}"
    return None


# ============================================================
# 测试函数（每个独立，出错不影响其他）
# ============================================================

def test_accuracy() -> Dict[str, Any]:
    """
    唤醒准确率测试：用测试音频检测关键词命中情况。
    使用 test_keywords.txt 中定义的关键词，对 0.wav-6.wav 进行检测。
    """
    result: Dict[str, Any] = {"test": "唤醒准确率", "status": "error"}
    try:
        wavs = _get_test_wavs()
        output, elapsed_ms = _run_kws(wavs, _TEST_KEYWORDS)
        detections = _parse_detections(output)

        # 统计每个 wav 的检测结果
        wav_results = {}
        for wav in wavs:
            wav_name = os.path.basename(wav)
            wav_dets = [d for d in detections if os.path.basename(d.get("wav_file", "")) == wav_name]
            wav_results[wav_name] = {
                "detected": len(wav_dets) > 0,
                "keywords": [d["keyword"] for d in wav_dets],
                "count": len(wav_dets),
            }

        total_wavs = len(wavs)
        wavs_with_hit = sum(1 for v in wav_results.values() if v["detected"])
        total_hits = sum(v["count"] for v in wav_results.values())

        result.update({
            "status": "ok",
            "total_wavs": total_wavs,
            "wavs_with_hit": wavs_with_hit,
            "total_keyword_hits": total_hits,
            "hit_rate_pct": round(wavs_with_hit / total_wavs * 100, 1) if total_wavs else 0,
            "elapsed_ms": round(elapsed_ms, 2),
            "details": wav_results,
        })
    except Exception as e:
        result["error"] = str(e)
    return result


def test_latency() -> Dict[str, Any]:
    """
    唤醒延迟测试：测量从音频开始到检测到关键词的时间。
    对每个音频重复 N 次取平均。
    """
    result: Dict[str, Any] = {"test": "唤醒延迟", "status": "error"}
    try:
        wavs = _get_test_wavs()
        latency_records: List[Dict[str, Any]] = []

        for wav in wavs:
            wav_name = os.path.basename(wav)
            run_latencies: List[float] = []
            first_timestamps: List[float] = []

            for _ in range(_REPEAT):
                output, wall_ms = _run_kws([wav], _TEST_KEYWORDS)
                detections = _parse_detections(output)
                if detections:
                    # 第一个检测到的关键词的第一个 token 时间戳（秒）-> 毫秒
                    first_det = detections[0]
                    timestamps = first_det.get("timestamps", [])
                    if timestamps:
                        first_ts_ms = timestamps[0] * 1000.0
                        first_timestamps.append(first_ts_ms)
                    run_latencies.append(wall_ms)

            if first_timestamps:
                avg_first_ts = sum(first_timestamps) / len(first_timestamps)
                avg_wall = sum(run_latencies) / len(run_latencies)
                latency_records.append({
                    "wav": wav_name,
                    "avg_first_token_ms": round(avg_first_ts, 2),
                    "avg_wall_ms": round(avg_wall, 2),
                    "runs": len(first_timestamps),
                })

        # 全局平均
        all_first_ts = [r["avg_first_token_ms"] for r in latency_records]
        avg_latency_ms = round(sum(all_first_ts) / len(all_first_ts), 2) if all_first_ts else 0

        result.update({
            "status": "ok",
            "avg_detection_latency_ms": avg_latency_ms,
            "per_wav": latency_records,
            "repeat": _REPEAT,
        })
    except Exception as e:
        result["error"] = str(e)
    return result


def test_cpu_usage() -> Dict[str, Any]:
    """
    CPU 占用测试：运行 KWS 时的 CPU 使用率。
    通过 /proc/<pid>/stat 采样 CPU 时间计算。
    """
    result: Dict[str, Any] = {"test": "CPU 占用", "status": "error"}
    try:
        wavs = _get_test_wavs()
        cmd = [
            _SHERPA_BIN,
            f"--encoder={_KWS_ENCODER}",
            f"--decoder={_KWS_DECODER}",
            f"--joiner={_KWS_JOINER}",
            f"--tokens={_KWS_TOKENS}",
            f"--keywords-file={_TEST_KEYWORDS}",
            f"--num-threads={_NUM_THREADS}",
        ] + wavs

        env = _build_env()

        cpu_percents: List[float] = []
        for _ in range(_REPEAT):
            t0 = time.monotonic()
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            )

            # 采集 /proc/<pid>/stat 的 utime + stime（单位: clock ticks）
            clk_tck = os.sysconf("SC_CLK_TCK")
            samples: List[Tuple[float, int]] = []
            while proc.poll() is None:
                try:
                    with open(f"/proc/{proc.pid}/stat", "r") as f:
                        fields = f.read().split()
                    # utime=field[13], stime=field[14] （从0开始）
                    utime = int(fields[13])
                    stime = int(fields[14])
                    total_ticks = utime + stime
                    samples.append((time.monotonic(), total_ticks))
                except Exception:
                    pass
                time.sleep(0.02)

            wall_s = time.monotonic() - t0
            proc.wait(timeout=5)

            if len(samples) >= 2 and wall_s > 0:
                cpu_ticks = samples[-1][1] - samples[0][1]
                cpu_s = cpu_ticks / clk_tck
                cpu_pct = (cpu_s / wall_s) * 100.0
                cpu_percents.append(cpu_pct)

        avg_cpu_pct = round(sum(cpu_percents) / len(cpu_percents), 1) if cpu_percents else 0

        result.update({
            "status": "ok",
            "avg_cpu_percent": avg_cpu_pct,
            "num_threads": _NUM_THREADS,
            "samples": len(cpu_percents),
            "note": "100% = 1 核满载",
        })
    except Exception as e:
        result["error"] = str(e)
    return result


def test_memory() -> Dict[str, Any]:
    """
    内存占用测试：测量 KWS 运行时的峰值 RSS 内存。
    """
    result: Dict[str, Any] = {"test": "内存占用", "status": "error"}
    try:
        wavs = _get_test_wavs()
        cmd = [
            _SHERPA_BIN,
            f"--encoder={_KWS_ENCODER}",
            f"--decoder={_KWS_DECODER}",
            f"--joiner={_KWS_JOINER}",
            f"--tokens={_KWS_TOKENS}",
            f"--keywords-file={_TEST_KEYWORDS}",
            f"--num-threads={_NUM_THREADS}",
        ] + wavs

        peak_rss_values: List[int] = []
        for _ in range(_REPEAT):
            info = _monitor_resources(cmd)
            peak_rss_values.append(info["peak_rss_kb"])

        avg_peak_kb = sum(peak_rss_values) // len(peak_rss_values) if peak_rss_values else 0
        max_peak_kb = max(peak_rss_values) if peak_rss_values else 0

        result.update({
            "status": "ok",
            "avg_peak_rss_mb": round(avg_peak_kb / 1024.0, 1),
            "max_peak_rss_mb": round(max_peak_kb / 1024.0, 1),
            "repeat": _REPEAT,
        })
    except Exception as e:
        result["error"] = str(e)
    return result


def test_false_alarm() -> Dict[str, Any]:
    """
    误唤醒率测试：用不含唤醒词的音频（ASR 测试音频）检测误触发。
    使用项目实际 keywords.txt（含"小医"）进行检测。
    """
    result: Dict[str, Any] = {"test": "误唤醒率", "status": "error"}
    try:
        fa_wavs = _get_false_alarm_wavs()
        if not fa_wavs:
            result["status"] = "skip"
            result["reason"] = f"未找到误唤醒测试音频: {_FALSE_ALARM_WAV_DIR}"
            return result

        # 使用项目实际的 keywords.txt（含"小医"）
        project_keywords = os.path.join(_KWS_DIR, "keywords.txt")
        if not os.path.isfile(project_keywords):
            # 也尝试 test_keywords
            project_keywords = _TEST_KEYWORDS

        total_false_alarms = 0
        total_runs = 0
        per_wav: List[Dict[str, Any]] = []

        for wav in fa_wavs:
            wav_name = os.path.basename(wav)
            fa_count = 0
            for _ in range(_REPEAT):
                output, _ = _run_kws([wav], project_keywords)
                detections = _parse_detections(output)
                fa_count += len(detections)
                total_runs += 1

            total_false_alarms += fa_count
            per_wav.append({
                "wav": wav_name,
                "false_alarms": fa_count,
                "runs": _REPEAT,
            })

        fa_rate = round(total_false_alarms / total_runs * 100, 2) if total_runs else 0

        result.update({
            "status": "ok",
            "total_test_wavs": len(fa_wavs),
            "total_runs": total_runs,
            "total_false_alarms": total_false_alarms,
            "false_alarm_rate_pct": fa_rate,
            "keywords_file": project_keywords,
            "per_wav": per_wav,
        })
    except Exception as e:
        result["error"] = str(e)
    return result


def test_miss_rate() -> Dict[str, Any]:
    """
    漏唤醒率测试：对包含唤醒词的音频多次检测，统计漏检次数。
    使用 test_keywords.txt 中的关键词。
    """
    result: Dict[str, Any] = {"test": "漏唤醒率", "status": "error"}
    try:
        wavs = _get_test_wavs()
        total_expected = 0
        total_missed = 0
        per_wav: List[Dict[str, Any]] = []

        for wav in wavs:
            wav_name = os.path.basename(wav)
            # 先跑一次确认该 wav 中应有几个关键词
            output_ref, _ = _run_kws([wav], _TEST_KEYWORDS)
            dets_ref = _parse_detections(output_ref)
            expected_count = len(dets_ref)

            if expected_count == 0:
                # 该 wav 没有匹配的关键词，跳过
                per_wav.append({
                    "wav": wav_name,
                    "expected": 0,
                    "missed": 0,
                    "runs": 0,
                    "note": "无预期关键词",
                })
                continue

            miss_count = 0
            run_counts: List[int] = []
            for _ in range(_REPEAT):
                output, _ = _run_kws([wav], _TEST_KEYWORDS)
                detections = _parse_detections(output)
                actual = len(detections)
                run_counts.append(actual)
                if actual < expected_count:
                    miss_count += (expected_count - actual)

            total_expected += expected_count * _REPEAT
            total_missed += miss_count

            per_wav.append({
                "wav": wav_name,
                "expected_per_run": expected_count,
                "runs": _REPEAT,
                "detection_counts": run_counts,
                "missed": miss_count,
            })

        miss_rate = round(total_missed / total_expected * 100, 2) if total_expected else 0

        result.update({
            "status": "ok",
            "total_expected": total_expected,
            "total_missed": total_missed,
            "miss_rate_pct": miss_rate,
            "per_wav": per_wav,
        })
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# 汇总与输出
# ============================================================

def _format_markdown(results: Dict[str, Any]) -> str:
    """将结果格式化为 Markdown 表格。"""
    lines = [
        "# KWS Benchmark 结果",
        "",
    ]

    # 总览表
    lines += [
        "## 总览",
        "",
        "| 测试项 | 关键指标 | 值 | 状态 |",
        "|--------|----------|-----|------|",
    ]

    acc = results.get("accuracy", {})
    if acc.get("status") == "ok":
        lines.append(
            f"| 唤醒准确率 | 命中率 | {acc['hit_rate_pct']}% "
            f"({acc['wavs_with_hit']}/{acc['total_wavs']}) | ✅ |"
        )
    else:
        lines.append(f"| 唤醒准确率 | - | {acc.get('error', 'N/A')} | ❌ |")

    lat = results.get("latency", {})
    if lat.get("status") == "ok":
        lines.append(
            f"| 唤醒延迟 | 平均首token时间 | {lat['avg_detection_latency_ms']} ms | ✅ |"
        )
    else:
        lines.append(f"| 唤醒延迟 | - | {lat.get('error', 'N/A')} | ❌ |")

    cpu = results.get("cpu", {})
    if cpu.get("status") == "ok":
        lines.append(f"| CPU 占用 | 平均 CPU | {cpu['avg_cpu_percent']}% | ✅ |")
    else:
        lines.append(f"| CPU 占用 | - | {cpu.get('error', 'N/A')} | ❌ |")

    mem = results.get("memory", {})
    if mem.get("status") == "ok":
        lines.append(
            f"| 内存占用 | 峰值 RSS | {mem['avg_peak_rss_mb']} MB "
            f"(max {mem['max_peak_rss_mb']} MB) | ✅ |"
        )
    else:
        lines.append(f"| 内存占用 | - | {mem.get('error', 'N/A')} | ❌ |")

    fa = results.get("false_alarm", {})
    if fa.get("status") == "ok":
        lines.append(f"| 误唤醒率 | 误报率 | {fa['false_alarm_rate_pct']}% "
                      f"({fa['total_false_alarms']}/{fa['total_runs']} 次) | ✅ |")
    elif fa.get("status") == "skip":
        lines.append(f"| 误唤醒率 | - | 跳过: {fa.get('reason', '')} | ⏭️ |")
    else:
        lines.append(f"| 误唤醒率 | - | {fa.get('error', 'N/A')} | ❌ |")

    mr = results.get("miss_rate", {})
    if mr.get("status") == "ok":
        lines.append(f"| 漏唤醒率 | 漏检率 | {mr['miss_rate_pct']}% "
                      f"({mr['total_missed']}/{mr['total_expected']} 次) | ✅ |")
    else:
        lines.append(f"| 漏唤醒率 | - | {mr.get('error', 'N/A')} | ❌ |")

    lines.append("")

    # 延迟详情
    if lat.get("status") == "ok" and lat.get("per_wav"):
        lines += [
            "## 延迟详情",
            "",
            "| 音频 | 平均首token延迟 (ms) | 平均总耗时 (ms) | 有效轮数 |",
            "|------|----------------------|----------------|----------|",
        ]
        for item in lat["per_wav"]:
            lines.append(
                f"| {item['wav']} | {item['avg_first_token_ms']} | "
                f"{item['avg_wall_ms']} | {item['runs']} |"
            )
        lines.append("")

    # 准确率详情
    if acc.get("status") == "ok" and acc.get("details"):
        lines += [
            "## 准确率详情",
            "",
            "| 音频 | 命中 | 检测到的关键词 |",
            "|------|------|---------------|",
        ]
        for wav_name, info in acc["details"].items():
            hit_str = "✅" if info["detected"] else "❌"
            kws_str = ", ".join(info["keywords"]) if info["keywords"] else "-"
            lines.append(f"| {wav_name} | {hit_str} | {kws_str} |")
        lines.append("")

    # 漏检详情
    if mr.get("status") == "ok" and mr.get("per_wav"):
        lines += [
            "## 漏检详情",
            "",
            "| 音频 | 预期/次 | 实际检测数 | 漏检 |",
            "|------|---------|-----------|------|",
        ]
        for item in mr["per_wav"]:
            counts_str = str(item.get("detection_counts", item.get("note", "-")))
            lines.append(
                f"| {item['wav']} | {item.get('expected_per_run', 0)} | "
                f"{counts_str} | {item['missed']} |"
            )
        lines.append("")

    # 配置信息
    lines += [
        "## 测试配置",
        "",
        f"- 可执行文件: `{_SHERPA_BIN}`",
        f"- 模型目录: `{_KWS_DIR}`",
        f"- 测试音频: `{_TEST_WAV_DIR}`",
        f"- 关键词文件: `{_TEST_KEYWORDS}`",
        f"- 推理线程数: {_NUM_THREADS}",
        f"- 每项重复: {_REPEAT} 次",
        "",
    ]

    return "\n".join(lines)


def main() -> Dict[str, Any]:
    """
    运行所有 KWS benchmark 测试。

    返回包含所有测试结果的 dict，可供 run_all_benchmarks.py 汇总使用。
    独立运行时在末尾打印 Markdown 格式的结果表。
    """
    print("=" * 60)
    print("  KWS (唤醒词检测) Benchmark")
    print("=" * 60)

    # 前置检查
    err = _check_prerequisites()
    if err:
        print(f"\n❌ 前置检查失败:\n{err}")
        return {"kws_benchmark": "error", "error": err}

    print(f"\n测试音频目录: {_TEST_WAV_DIR}")
    print(f"测试音频数量: {len(_get_test_wavs())}")
    print(f"误唤醒音频数量: {len(_get_false_alarm_wavs())}")
    print(f"每项重复次数: {_REPEAT}")
    print()

    results: Dict[str, Any] = {}

    # 1. 唤醒准确率
    print("[1/6] 唤醒准确率测试...")
    results["accuracy"] = test_accuracy()
    acc = results["accuracy"]
    if acc["status"] == "ok":
        print(f"  → 命中率: {acc['hit_rate_pct']}% ({acc['wavs_with_hit']}/{acc['total_wavs']})")
        print(f"  → 共检测到 {acc['total_keyword_hits']} 个关键词, 耗时 {acc['elapsed_ms']:.0f} ms")
    else:
        print(f"  → 失败: {acc.get('error', 'unknown')}")

    # 2. 唤醒延迟
    print("[2/6] 唤醒延迟测试...")
    results["latency"] = test_latency()
    lat = results["latency"]
    if lat["status"] == "ok":
        print(f"  → 平均首token延迟: {lat['avg_detection_latency_ms']} ms")
    else:
        print(f"  → 失败: {lat.get('error', 'unknown')}")

    # 3. CPU 占用
    print("[3/6] CPU 占用测试...")
    results["cpu"] = test_cpu_usage()
    cpu = results["cpu"]
    if cpu["status"] == "ok":
        print(f"  → 平均 CPU 使用率: {cpu['avg_cpu_percent']}% ({cpu['num_threads']} 线程)")
    else:
        print(f"  → 失败: {cpu.get('error', 'unknown')}")

    # 4. 内存占用
    print("[4/6] 内存占用测试...")
    results["memory"] = test_memory()
    mem = results["memory"]
    if mem["status"] == "ok":
        print(f"  → 平均峰值 RSS: {mem['avg_peak_rss_mb']} MB (最大 {mem['max_peak_rss_mb']} MB)")
    else:
        print(f"  → 失败: {mem.get('error', 'unknown')}")

    # 5. 误唤醒率
    print("[5/6] 误唤醒率测试...")
    results["false_alarm"] = test_false_alarm()
    fa = results["false_alarm"]
    if fa["status"] == "ok":
        print(f"  → 误唤醒率: {fa['false_alarm_rate_pct']}% "
              f"({fa['total_false_alarms']}/{fa['total_runs']} 次)")
    elif fa["status"] == "skip":
        print(f"  → 跳过: {fa.get('reason', '')}")
    else:
        print(f"  → 失败: {fa.get('error', 'unknown')}")

    # 6. 漏唤醒率
    print("[6/6] 漏唤醒率测试...")
    results["miss_rate"] = test_miss_rate()
    mr = results["miss_rate"]
    if mr["status"] == "ok":
        print(f"  → 漏唤醒率: {mr['miss_rate_pct']}% "
              f"({mr['total_missed']}/{mr['total_expected']} 次)")
    else:
        print(f"  → 失败: {mr.get('error', 'unknown')}")

    print("\n" + "=" * 60)
    print("  测试完成")
    print("=" * 60)

    # 独立运行时打印 Markdown
    if __name__ == "__main__" or "benchmark_kws" in sys.argv[0]:
        md = _format_markdown(results)
        print("\n" + md)

    return results


if __name__ == "__main__":
    main()
