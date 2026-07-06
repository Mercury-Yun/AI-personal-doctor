#!/usr/bin/env python3
"""TTS 性能 benchmark 脚本

对比云端 TTS (DashScope CosyVoice) 和本地 TTS (Piper) 的合成性能。
"""

import os
import sys

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_tts.py

import subprocess
import tempfile
import time
import resource

# 将项目根目录加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 测试文本（不同长度）
TEST_TEXTS = [
    "您好，该吃降压药了。",
    "我在呢，请问哪里不舒服？",
    "您的血压偏高，建议注意休息，减少盐分摄入。",
    "今天的健康评分是八十五分，整体状况良好。",
    "根据您的描述，建议您尽快到医院做进一步检查。",
    "高血压患者日常应注意低盐饮食，适当运动，保持良好的心态，按时服药，定期测量血压。",
    "我在呢",
    "来了",
]

# 本地 Piper 路径配置
PIPER_BINARY = "/home/elf/Qwen_test/piper/piper"
PIPER_MODEL = "/home/elf/Qwen_test/piper/zh_CN-huayan-medium.onnx"
PIPER_LIB_DIR = "/home/elf/Qwen_test/piper/"

# 音频参数：22050Hz, 16bit, 单声道 → 每秒 44100 字节
BYTES_PER_SECOND = 44100
WAV_HEADER_SIZE = 44


def _calc_audio_duration_from_size(file_size: int) -> float:
    """根据 WAV 文件大小计算音频时长（秒）"""
    pcm_size = file_size - WAV_HEADER_SIZE
    if pcm_size <= 0:
        return 0.0
    return pcm_size / BYTES_PER_SECOND


def _calc_audio_duration_from_bytes(data: bytes) -> float:
    """根据音频 bytes 计算音频时长（秒）"""
    pcm_size = len(data) - WAV_HEADER_SIZE
    if pcm_size <= 0:
        return 0.0
    return pcm_size / BYTES_PER_SECOND


def benchmark_cloud_tts() -> dict:
    """测试云端 TTS (CosyVoice) 性能"""
    try:
        from backend.services.cloud_tts_service import cloud_tts_configured, synthesize_bytes
    except ImportError:
        return {"skipped": True, "reason": "无法导入 cloud_tts_service 模块"}

    if not cloud_tts_configured():
        return {"skipped": True, "reason": "云端 TTS 未配置（DASHSCOPE_API_KEY 缺失）"}

    results = []
    for text in TEST_TEXTS:
        t_start = time.monotonic()
        audio_data = synthesize_bytes(text)
        t_end = time.monotonic()

        synth_time = t_end - t_start
        audio_duration = _calc_audio_duration_from_bytes(audio_data)
        rtf = synth_time / audio_duration if audio_duration > 0 else float("inf")

        results.append({
            "text": text,
            "text_len": len(text),
            "synth_time_s": round(synth_time, 3),
            "audio_bytes": len(audio_data),
            "audio_duration_s": round(audio_duration, 3),
            "rtf": round(rtf, 3),
        })

    # 计算平均值
    avg_synth_time = sum(r["synth_time_s"] for r in results) / len(results)
    avg_rtf = sum(r["rtf"] for r in results) / len(results)

    return {
        "skipped": False,
        "engine": "CosyVoice (DashScope)",
        "model": "cosyvoice-v3-flash",
        "voice": "longanhuan",
        "sample_rate": 22050,
        "note": "同步接口，无法测量首包延迟，总耗时即为完整延迟",
        "results": results,
        "avg_synth_time_s": round(avg_synth_time, 3),
        "avg_rtf": round(avg_rtf, 3),
    }


def benchmark_piper_tts() -> dict:
    """测试本地 TTS (Piper) 性能"""
    if not os.path.isfile(PIPER_BINARY):
        return {"skipped": True, "reason": f"Piper 二进制不存在: {PIPER_BINARY}"}
    if not os.path.isfile(PIPER_MODEL):
        return {"skipped": True, "reason": f"Piper 模型不存在: {PIPER_MODEL}"}

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = PIPER_LIB_DIR + ":" + env.get("LD_LIBRARY_PATH", "")

    results = []
    for text in TEST_TEXTS:
        # 输出到临时文件
        tmp_wav = tempfile.mktemp(suffix=".wav", prefix="benchmark_piper_")
        cmd = [
            PIPER_BINARY,
            "--model", PIPER_MODEL,
            "--output_file", tmp_wav,
            "--quiet",
        ]

        try:
            t_start = time.monotonic()
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
            )
            proc.communicate(input=text.encode("utf-8"))
            t_end = time.monotonic()

            synth_time = t_end - t_start

            # 获取峰值内存（通过 /proc 读取子进程已结束，使用父进程 ru_maxrss 近似）
            # 使用 resource 模块获取子进程资源使用
            child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            peak_rss_kb = child_usage.ru_maxrss  # 单位: KB (Linux)

            # 计算音频时长
            if os.path.isfile(tmp_wav):
                file_size = os.path.getsize(tmp_wav)
                audio_duration = _calc_audio_duration_from_size(file_size)
            else:
                file_size = 0
                audio_duration = 0.0

            rtf = synth_time / audio_duration if audio_duration > 0 else float("inf")

            results.append({
                "text": text,
                "text_len": len(text),
                "synth_time_s": round(synth_time, 3),
                "file_size_bytes": file_size,
                "audio_duration_s": round(audio_duration, 3),
                "rtf": round(rtf, 3),
                "peak_rss_mb": round(peak_rss_kb / 1024, 1),
            })
        finally:
            # 清理临时文件
            if os.path.isfile(tmp_wav):
                os.unlink(tmp_wav)

    # 计算平均值
    avg_synth_time = sum(r["synth_time_s"] for r in results) / len(results)
    avg_rtf = sum(r["rtf"] for r in results) / len(results)
    max_rss = max(r["peak_rss_mb"] for r in results)

    return {
        "skipped": False,
        "engine": "Piper (本地)",
        "model": "zh_CN-huayan-medium",
        "sample_rate": 22050,
        "results": results,
        "avg_synth_time_s": round(avg_synth_time, 3),
        "avg_rtf": round(avg_rtf, 3),
        "peak_rss_mb": max_rss,
    }


def format_markdown_report(cloud_result: dict, piper_result: dict) -> str:
    """生成 Markdown 格式的性能报告"""
    lines = []
    lines.append("# TTS 性能 Benchmark 报告\n")
    lines.append(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 云端 TTS 结果
    lines.append("## 云端 TTS (CosyVoice)\n")
    if cloud_result.get("skipped"):
        lines.append(f"> 已跳过: {cloud_result['reason']}\n")
    else:
        lines.append(f"- 引擎: {cloud_result['engine']}")
        lines.append(f"- 模型: {cloud_result['model']}")
        lines.append(f"- 音色: {cloud_result['voice']}")
        lines.append(f"- 采样率: {cloud_result['sample_rate']} Hz")
        lines.append(f"- 备注: {cloud_result['note']}")
        lines.append("")
        lines.append("| 文本 | 字数 | 合成耗时(s) | 音频时长(s) | RTF |")
        lines.append("|------|------|-------------|-------------|-----|")
        for r in cloud_result["results"]:
            lines.append(
                f"| {r['text'][:15]}... | {r['text_len']} | {r['synth_time_s']} | "
                f"{r['audio_duration_s']} | {r['rtf']} |"
            )
        lines.append("")
        lines.append(f"**平均合成耗时: {cloud_result['avg_synth_time_s']}s | 平均 RTF: {cloud_result['avg_rtf']}**\n")

    # 本地 TTS 结果
    lines.append("## 本地 TTS (Piper)\n")
    if piper_result.get("skipped"):
        lines.append(f"> 已跳过: {piper_result['reason']}\n")
    else:
        lines.append(f"- 引擎: {piper_result['engine']}")
        lines.append(f"- 模型: {piper_result['model']}")
        lines.append(f"- 采样率: {piper_result['sample_rate']} Hz")
        lines.append("")
        lines.append("| 文本 | 字数 | 合成耗时(s) | 音频时长(s) | RTF | 峰值RSS(MB) |")
        lines.append("|------|------|-------------|-------------|-----|-------------|")
        for r in piper_result["results"]:
            lines.append(
                f"| {r['text'][:15]}... | {r['text_len']} | {r['synth_time_s']} | "
                f"{r['audio_duration_s']} | {r['rtf']} | {r['peak_rss_mb']} |"
            )
        lines.append("")
        lines.append(
            f"**平均合成耗时: {piper_result['avg_synth_time_s']}s | "
            f"平均 RTF: {piper_result['avg_rtf']} | "
            f"峰值内存: {piper_result['peak_rss_mb']} MB**\n"
        )

    # 对比总结
    lines.append("## 对比总结\n")
    lines.append("| 指标 | 云端 CosyVoice | 本地 Piper |")
    lines.append("|------|----------------|------------|")
    cloud_avg = cloud_result.get("avg_synth_time_s", "N/A")
    piper_avg = piper_result.get("avg_synth_time_s", "N/A")
    cloud_rtf = cloud_result.get("avg_rtf", "N/A")
    piper_rtf = piper_result.get("avg_rtf", "N/A")
    piper_mem = piper_result.get("peak_rss_mb", "N/A")
    lines.append(f"| 平均合成耗时 | {cloud_avg}s | {piper_avg}s |")
    lines.append(f"| 平均 RTF | {cloud_rtf} | {piper_rtf} |")
    lines.append(f"| 峰值内存 | - (云端) | {piper_mem} MB |")
    lines.append(f"| 网络依赖 | 是 | 否 |")
    lines.append("")

    return "\n".join(lines)


def main() -> dict:
    """运行完整 benchmark，返回结果 dict 并打印 Markdown 报告"""
    print("=" * 60)
    print("  TTS 性能 Benchmark")
    print("=" * 60)
    print()

    # 云端 TTS 测试
    print("[1/2] 测试云端 TTS (CosyVoice)...")
    cloud_result = benchmark_cloud_tts()
    if cloud_result.get("skipped"):
        print(f"  ⏭ 已跳过: {cloud_result['reason']}")
    else:
        print(f"  ✓ 完成，平均耗时 {cloud_result['avg_synth_time_s']}s, RTF={cloud_result['avg_rtf']}")
    print()

    # 本地 TTS 测试
    print("[2/2] 测试本地 TTS (Piper)...")
    piper_result = benchmark_piper_tts()
    if piper_result.get("skipped"):
        print(f"  ⏭ 已跳过: {piper_result['reason']}")
    else:
        print(f"  ✓ 完成，平均耗时 {piper_result['avg_synth_time_s']}s, RTF={piper_result['avg_rtf']}")
    print()

    # 生成报告
    print("-" * 60)
    report = format_markdown_report(cloud_result, piper_result)
    print(report)

    return {
        "cloud_tts": cloud_result,
        "piper_tts": piper_result,
    }


if __name__ == "__main__":
    main()
