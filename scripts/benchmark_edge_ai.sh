#!/bin/bash
# =============================================================================
# 边缘 AI Benchmark 脚本
# 测试项目中所有本地模型的推理速度、资源占用等指标
# 用法: bash scripts/benchmark_edge_ai.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
QWEN_DIR="/home/elf/Qwen_test"
SHERPA_BIN_DIR="$QWEN_DIR/sherpa/bin"
SHERPA_LIB_DIR="$QWEN_DIR/sherpa/lib"
SHERPA_ASR_DIR="$QWEN_DIR/sherpa/asr_sensevoice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SHERPA_KWS_DIR="$QWEN_DIR/sherpa/kws"
PIPER_DIR="$QWEN_DIR/piper"
REPORT_FILE="$PROJECT_DIR/benchmark_report.md"
TEMP_DIR="/tmp/benchmark_$$"

export LD_LIBRARY_PATH="$SHERPA_LIB_DIR:${LD_LIBRARY_PATH:-}"

mkdir -p "$TEMP_DIR"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  边缘 AI Benchmark - RK3588${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# 初始化报告
cat > "$REPORT_FILE" << 'HEADER'
# 边缘 AI Benchmark 报告

> 测试平台: RK3588 开发板
> 测试时间: TIMESTAMP
> 项目: AI 私人医生 (AI Personal Doctor)

---

HEADER
sed -i "s/TIMESTAMP/$(date '+%Y-%m-%d %H:%M:%S')/" "$REPORT_FILE"

# ==================== 系统信息 ====================
echo -e "${GREEN}[1/6] 采集系统信息...${NC}"
{
  echo "## 1. 系统信息"
  echo ""
  echo "| 项目 | 值 |"
  echo "|------|-----|"
  CPU_MODEL=$(lscpu 2>/dev/null | grep 'Model name' | head -1 | sed 's/Model name: *//' || echo 'N/A')
  echo "| CPU | ${CPU_MODEL} |"
  echo "| CPU 核心数 | $(nproc) |"
  echo "| 总内存 | $(free -h | awk '/Mem:/ {print $2}') |"
  echo "| 可用内存 | $(free -h | awk '/Mem:/ {print $7}') |"
  echo "| 内核 | $(uname -r) |"
  echo "| 架构 | $(uname -m) |"
  echo ""
} >> "$REPORT_FILE"

# ==================== ASR ====================
echo -e "${GREEN}[2/6] ASR Benchmark (Sherpa-ONNX SenseVoice)...${NC}"
{
  echo "## 2. ASR 语音识别 (Sherpa-ONNX SenseVoice)"
  echo ""
  echo "模型: SenseVoice (int8 量化)"
  echo ""
} >> "$REPORT_FILE"

ASR_BIN="$SHERPA_BIN_DIR/sherpa-onnx-offline"
ASR_MODEL="$SHERPA_ASR_DIR/model.int8.onnx"
ASR_TOKENS="$SHERPA_ASR_DIR/tokens.txt"
ASR_TEST_WAVS="$SHERPA_ASR_DIR/test_wavs"

if [ -f "$ASR_BIN" ] && [ -f "$ASR_MODEL" ]; then
  {
    echo "| 文件 | 音频时长(s) | 推理耗时(s) | RTF | 识别结果 |"
    echo "|------|------------|------------|-----|---------|"
  } >> "$REPORT_FILE"

  for wav_file in "$ASR_TEST_WAVS"/*.wav; do
    [ -f "$wav_file" ] || continue
    wav_name=$(basename "$wav_file")

    # sherpa-onnx-offline 自带 RTF 输出，直接解析即可
    OUTPUT=$("$ASR_BIN" \
      --sense-voice-model="$ASR_MODEL" \
      --tokens="$ASR_TOKENS" \
      --num-threads=2 \
      --sense-voice-use-itn=true \
      --sense-voice-language=zh \
      "$wav_file" 2>&1) || true

    # 解析 "Elapsed seconds: 0.408 s"
    ELAPSED=$(echo "$OUTPUT" | grep -o 'Elapsed seconds: [0-9.]*' | awk '{print $3}')
    # 解析 "Real time factor (RTF): 0.408 / 5.592 = 0.073"
    RTF=$(echo "$OUTPUT" | grep -o 'RTF.*= [0-9.]*' | awk -F'= ' '{print $2}')
    AUDIO_DUR=$(echo "$OUTPUT" | grep 'RTF' | grep -o '/ [0-9.]*' | awk '{print $2}')
    # 解析识别文本 {"text": "..."}
    TEXT=$(echo "$OUTPUT" | grep '"text"' | sed 's/.*"text": *"//;s/".*//' | head -1)
    [ ${#TEXT} -gt 40 ] && TEXT="${TEXT:0:40}..."

    echo "| ${wav_name} | ${AUDIO_DUR:-N/A} | ${ELAPSED:-N/A} | ${RTF:-N/A} | ${TEXT:-N/A} |" >> "$REPORT_FILE"
    echo "  [${wav_name}] 推理=${ELAPSED:-?}s RTF=${RTF:-?}"
  done

  # 获取峰值内存：单独跑一次，用 /proc 监控
  "$ASR_BIN" --sense-voice-model="$ASR_MODEL" --tokens="$ASR_TOKENS" --num-threads=2 \
    "$ASR_TEST_WAVS/zh.wav" > /dev/null 2>&1 &
  ASR_PID=$!
  ASR_PEAK_MEM=0
  while kill -0 $ASR_PID 2>/dev/null; do
    MEM_KB=$(awk '/VmRSS/ {print $2}' /proc/$ASR_PID/status 2>/dev/null || echo 0)
    [ "$MEM_KB" -gt "$ASR_PEAK_MEM" ] && ASR_PEAK_MEM=$MEM_KB
    sleep 0.1
  done
  wait $ASR_PID 2>/dev/null || true
  ASR_PEAK_MB=$((ASR_PEAK_MEM / 1024))

  {
    echo ""
    echo "**峰值内存占用: ${ASR_PEAK_MB}MB**"
    echo ""
    echo "> RTF (Real Time Factor) < 1.0 表示快于实时，越小越快"
  } >> "$REPORT_FILE"
  echo "  ASR 测试完成 (峰值内存 ${ASR_PEAK_MB}MB)"
else
  echo "  跳过（未找到 sherpa-onnx-offline 或模型文件）"
  echo "跳过" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# ==================== KWS ====================
echo -e "${GREEN}[3/6] KWS Benchmark (唤醒词检测)...${NC}"
{
  echo "---"
  echo ""
  echo "## 3. KWS 唤醒词检测 (Sherpa-ONNX)"
  echo ""
  echo "模型: Zipformer Transducer (int8 量化)"
  echo ""
  echo "唤醒词: 小医"
  echo ""
} >> "$REPORT_FILE"

KWS_BIN="$SHERPA_BIN_DIR/sherpa-onnx-keyword-spotter"
KWS_ENCODER="$SHERPA_KWS_DIR/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
KWS_DECODER="$SHERPA_KWS_DIR/decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
KWS_JOINER="$SHERPA_KWS_DIR/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
KWS_TOKENS="$SHERPA_KWS_DIR/tokens.txt"
KWS_KEYWORDS="$SHERPA_KWS_DIR/test_wavs/test_keywords.txt"
KWS_TEST_WAVS="$SHERPA_KWS_DIR/test_wavs"

if [ -f "$KWS_BIN" ] && [ -f "$KWS_ENCODER" ]; then
  # 批量检测所有 wav
  T0=$(date +%s%N)
  KWS_OUTPUT=$("$KWS_BIN" \
    --encoder="$KWS_ENCODER" \
    --decoder="$KWS_DECODER" \
    --joiner="$KWS_JOINER" \
    --tokens="$KWS_TOKENS" \
    --keywords-file="$KWS_KEYWORDS" \
    --num-threads=2 \
    "$KWS_TEST_WAVS"/*.wav 2>&1) || true
  T1=$(date +%s%N)
  KWS_ELAPSED_MS=$(( (T1 - T0) / 1000000 ))

  # 统计检测到的关键词
  KWS_HITS=$(echo "$KWS_OUTPUT" | grep -c '"keyword"' || true)
  KWS_WAV_COUNT=$(ls "$KWS_TEST_WAVS"/*.wav 2>/dev/null | wc -l)

  # 获取峰值内存
  "$KWS_BIN" --encoder="$KWS_ENCODER" --decoder="$KWS_DECODER" --joiner="$KWS_JOINER" \
    --tokens="$KWS_TOKENS" --keywords-file="$KWS_KEYWORDS" --num-threads=2 \
    "$KWS_TEST_WAVS/0.wav" > /dev/null 2>&1 &
  KWS_PID=$!
  KWS_PEAK_MEM=0
  while kill -0 $KWS_PID 2>/dev/null; do
    MEM_KB=$(awk '/VmRSS/ {print $2}' /proc/$KWS_PID/status 2>/dev/null || echo 0)
    [ "$MEM_KB" -gt "$KWS_PEAK_MEM" ] && KWS_PEAK_MEM=$MEM_KB
    sleep 0.05
  done
  wait $KWS_PID 2>/dev/null || true
  KWS_PEAK_MB=$((KWS_PEAK_MEM / 1024))

  {
    echo "| 指标 | 值 |"
    echo "|------|-----|"
    echo "| 测试音频数 | ${KWS_WAV_COUNT} |"
    echo "| 检测到关键词数 | ${KWS_HITS} |"
    echo "| 总处理耗时 | ${KWS_ELAPSED_MS}ms |"
    echo "| 峰值内存占用 | ${KWS_PEAK_MB}MB |"
    echo ""
    echo "**检测到的关键词：**"
    echo ""
    echo '```'
    echo "$KWS_OUTPUT" | grep '"keyword"' || echo "无"
    echo '```'
  } >> "$REPORT_FILE"
  echo "  KWS 测试完成 (${KWS_HITS} 个关键词, ${KWS_ELAPSED_MS}ms, 内存 ${KWS_PEAK_MB}MB)"
else
  echo "  跳过（未找到模型文件）"
  echo "跳过" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# ==================== RKLLM ====================
echo -e "${GREEN}[4/6] RKLLM Benchmark (Qwen2-VL-2B NPU)...${NC}"
{
  echo "---"
  echo ""
  echo "## 4. RKLLM 大语言模型 (Qwen2-VL-2B NPU)"
  echo ""
  echo "模型: Qwen2-VL-2B-Instruct.rkllm"
  echo ""
  echo "推理后端: RK3588 NPU"
  echo ""
} >> "$REPORT_FILE"

LLM_BIN="$QWEN_DIR/llm_test"
LLM_MODEL="$QWEN_DIR/Qwen2-VL-2B-Instruct.rkllm"

if [ -f "$LLM_BIN" ] && [ -f "$LLM_MODEL" ]; then
  echo "  加载模型并测试推理 (max_tokens=128)..."

  T0=$(date +%s%N)
  LLM_OUTPUT=$(echo "你好，请简单介绍一下高血压的症状。" | timeout 180 "$LLM_BIN" "$LLM_MODEL" 128 512 2>&1 || true)
  T1=$(date +%s%N)
  LLM_ELAPSED_MS=$(( (T1 - T0) / 1000000 ))

  # 解析模型加载时间
  LOAD_TIME=$(echo "$LLM_OUTPUT" | grep -oi 'Model loaded in *[0-9.]*' | head -1 || true)
  [ -z "$LOAD_TIME" ] && LOAD_TIME=$(echo "$LLM_OUTPUT" | grep -oi 'load.*[0-9.]\+ *ms' | head -1 || true)
  [ -z "$LOAD_TIME" ] && LOAD_TIME="见总耗时"

  # 解析 tokens/s
  TOKEN_SPEED=$(echo "$LLM_OUTPUT" | grep -oi '[0-9.]\+ *tokens\?/s' | head -1 || true)
  [ -z "$TOKEN_SPEED" ] && TOKEN_SPEED="N/A"

  LLM_CHARS=$(echo "$LLM_OUTPUT" | wc -c)

  {
    echo "**测试 Prompt**: \"你好，请简单介绍一下高血压的症状。\""
    echo ""
    echo "**参数**: max_new_tokens=128, max_context_len=512"
    echo ""
    echo "| 指标 | 值 |"
    echo "|------|-----|"
    echo "| 总耗时 | ${LLM_ELAPSED_MS}ms |"
    echo "| 模型加载时间 | ${LOAD_TIME} |"
    echo "| 推理速度 | ${TOKEN_SPEED} |"
    echo "| 输出字符数 | ${LLM_CHARS} |"
    echo ""
    echo "<details>"
    echo "<summary>完整输出（点击展开）</summary>"
    echo ""
    echo '```'
    echo "$LLM_OUTPUT" | head -30
    echo '```'
    echo "</details>"
  } >> "$REPORT_FILE"
  echo "  RKLLM 测试完成 (${LLM_ELAPSED_MS}ms)"
else
  echo "  跳过（未找到 llm_test 或模型文件）"
  echo "跳过" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# ==================== Piper TTS ====================
echo -e "${GREEN}[5/6] Piper TTS Benchmark (本地语音合成)...${NC}"
{
  echo "---"
  echo ""
  echo "## 5. Piper TTS 本地语音合成"
  echo ""
  echo "模型: zh_CN-huayan-medium"
  echo ""
} >> "$REPORT_FILE"

PIPER_BIN="$PIPER_DIR/piper"

if [ -f "$PIPER_BIN" ]; then
  TEST_SENTENCES=(
    "您好，该吃降压药了。"
    "您的血压偏高，建议注意休息，减少盐分摄入。"
    "今天的健康评分是八十五分，整体状况良好。"
    "我在呢，请问哪里不舒服？"
    "根据您的描述，建议您尽快到医院做进一步检查。"
  )

  {
    echo "| 序号 | 文本 | 字数 | 合成耗时(ms) | 音频时长(s) | RTF |"
    echo "|------|------|------|-------------|------------|-----|"
  } >> "$REPORT_FILE"

  TOTAL_SYNTH=0
  IDX=0

  for sent in "${TEST_SENTENCES[@]}"; do
    IDX=$((IDX + 1))
    OUT_WAV="$TEMP_DIR/tts_${IDX}.wav"
    CHAR_COUNT=${#sent}

    T_START=$(date +%s%N)
    echo "$sent" | LD_LIBRARY_PATH="$PIPER_DIR" "$PIPER_BIN" \
      --model "$PIPER_DIR/zh_CN-huayan-medium.onnx" \
      --output_file "$OUT_WAV" \
      --quiet 2>/dev/null || true
    T_END=$(date +%s%N)
    SYNTH_MS=$(( (T_END - T_START) / 1000000 ))

    # 从 WAV 文件大小计算音频时长
    # Piper 输出: 22050Hz, 16bit, 单声道 => 每秒 44100 字节
    AUDIO_DUR="0"
    RTF="N/A"
    if [ -f "$OUT_WAV" ]; then
      FILE_SIZE=$(stat -c%s "$OUT_WAV" 2>/dev/null || echo "0")
      if [ "$FILE_SIZE" -gt 44 ] 2>/dev/null; then
        AUDIO_DUR=$(awk "BEGIN {printf \"%.2f\", ($FILE_SIZE - 44) / 44100}")
        RTF=$(awk "BEGIN {printf \"%.4f\", ($SYNTH_MS / 1000) / (($FILE_SIZE - 44) / 44100)}")
      fi
    fi

    TOTAL_SYNTH=$((TOTAL_SYNTH + SYNTH_MS))

    SENT_SHORT="${sent:0:16}"
    echo "| $IDX | ${SENT_SHORT}... | $CHAR_COUNT | $SYNTH_MS | $AUDIO_DUR | $RTF |" >> "$REPORT_FILE"
    echo "  [$IDX/5] ${SYNTH_MS}ms → ${AUDIO_DUR}s (RTF=${RTF})"
  done

  AVG_SYNTH=$((TOTAL_SYNTH / ${#TEST_SENTENCES[@]}))
  {
    echo ""
    echo "**平均合成耗时: ${AVG_SYNTH}ms**"
    echo ""
    echo "> RTF < 1.0 表示合成速度快于实时播放速度"
  } >> "$REPORT_FILE"
  echo "  Piper TTS 测试完成 (平均 ${AVG_SYNTH}ms)"
else
  echo "  跳过（未找到 piper）"
  echo "跳过" >> "$REPORT_FILE"
fi
echo "" >> "$REPORT_FILE"

# ==================== 系统资源基线 ====================
echo -e "${GREEN}[6/6] 系统资源基线...${NC}"
{
  echo "---"
  echo ""
  echo "## 6. 系统资源基线"
  echo ""
  echo "| 指标 | 值 |"
  echo "|------|-----|"
  echo "| CPU 空闲率 | $(top -bn1 | grep 'Cpu(s)' | awk '{print $8}' 2>/dev/null || echo 'N/A')% |"
  echo "| 已用内存 | $(free -h | awk '/Mem:/ {print $3}') / $(free -h | awk '/Mem:/ {print $2}') |"
  echo "| 可用内存 | $(free -h | awk '/Mem:/ {print $7}') |"
  echo "| 系统负载 | $(uptime | awk -F'load average:' '{print $2}' | xargs) |"
  echo "| 磁盘使用 | $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}') |"
  echo ""
} >> "$REPORT_FILE"

# 清理
rm -rf "$TEMP_DIR"

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Benchmark 完成！${NC}"
echo -e "${CYAN}  报告已保存到: $REPORT_FILE${NC}"
echo -e "${CYAN}========================================${NC}"
