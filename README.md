# AI 私人医生（AI Personal Doctor）

面向 **RK3588 边缘计算平台** 的 AI 私人医生系统：端侧本地模型（唤醒 / 语音识别 / 语音合成 / 视觉大模型）与云端大模型（通义千问 DashScope）协同，为家庭 / 老人提供健康档案管理、用药提醒、语音问诊、拍照问药与紧急求助等能力。

> 嵌入式竞赛作品 · 边缘 AI 能力（推理速度 / 识别准确率 / 资源占用）见 [第 9 节 边缘 AI 性能](#9-边缘-ai-性能benchmark)。

---

## 1. 功能亮点

- **健康 Dashboard**：Apple Health 风格大屏，展示健康评分、今日用药、待办提醒与 ECharts 趋势图。
- **健康档案 / 病例 / 药物管理**：增删改查，数据持久化到 SQLite，支持按患者筛选。
- **用药提醒**：按服药时间调度，到点弹窗 + TTS 播报，支持「已服用」确认与重复提醒。
- **语音问诊**：唤醒词「**小医**」→ 语音识别 → RAG 知识检索 → LLM 回答 → 语音播报，支持多轮连续对话。
- **拍照问药**：进入界面即开摄像头 **MJPEG 实时预览**，语音「两秒后拍照」倒计时期间实时对焦，拍照后由视觉大模型识别药名、用法用量与注意事项，支持追问与「换一个」。
- **SOS 紧急求助**：一键通过 Server 酱推送微信消息给家属。
- **每日健康日报**：定时汇总当日健康指标 + 用药情况 + 问诊记录，推送到家属微信。
- **佳明手表数据接入**：通过 Garmin 账号同步心率、步数等健康指标。

## 2. 系统架构

```
        ┌──────────────────────── RK3588 板端 ────────────────────────┐
        │                                                             │
  用户 ──┤  麦克风 ─▶ KWS 唤醒(小医) ─▶ ASR ─┐                          │
        │  摄像头 ─▶ MJPEG 实时流 ──────────┤                          │
        │                                  ▼                          │
        │   Vue3 大屏 (5173) ──/api──▶ FastAPI (8000) ── SQLite       │
        │        ▲                          │                         │
        │        │  TTS(Piper/CosyVoice)    │                         │
        └────────┼──────────────────────────┼─────────────────────────┘
                 │                          ▼
            本地 NPU 推理            云端 DashScope（通义千问）
         (Qwen2-VL / Sherpa)      LLM · VLM · CosyVoice TTS
```

- **端侧（本地）**：唤醒、语音识别、语音合成、视觉大模型均可在板上 NPU/CPU 运行，保证低延迟与离线可用。
- **云端**：文本问诊、拍照识图、语音合成可切换到 DashScope，获得更高的回答质量。
- 云 / 端由环境变量热切换（见 [第 6 节](#6-环境变量)），互为降级备份。

## 3. 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue3 + Vite + Vue Router + Pinia + Element Plus + ECharts |
| 后端 | FastAPI + SQLAlchemy + SQLite |
| RAG | FAISS + sentence-transformers（BAAI/bge-small-zh-v1.5） |
| 云端模型 | DashScope：Qwen（文本）/ Qwen-VL-Max（视觉）/ CosyVoice（TTS） |
| 端侧模型 | Sherpa-ONNX（KWS/ASR）、Piper（TTS）、Qwen2-VL-2B RKLLM（NPU 视觉） |
| 硬件接口 | OpenCV / fswebcam（摄像头）、arecord/aplay（音频） |

## 4. 端侧 AI 模型栈

| 能力 | 引擎 / 模型 | 说明 |
|------|-------------|------|
| 唤醒 (KWS) | Sherpa-ONNX 关键词检测 | 唤醒词「小医」，带 RMS 能量门控防误触发 |
| 语音识别 (ASR) | Sherpa-ONNX | 多语种，中文 CER ≈ 7.7%，RTF ≈ 0.04 |
| 语音合成 (TTS) | Piper（`zh_CN-huayan-medium`） | 本地实时合成，RTF ≈ 0.42 |
| 视觉大模型 (VLM) | Qwen2-VL-2B RKLLM | 板端 NPU 推理（拍照问药） |
| 知识检索 (RAG) | FAISS + bge-small-zh | 疾病 / 药品 / 急救 / 老年知识库 |

## 5. 项目结构

```text
src/                      # 前端 (Vue3)
  api/                    # 接口封装 (device.js / chat.js / users.js ...)
  views/
    Dashboard.vue         # 健康大屏
    DoctorChat.vue        # 语音问诊 (含 SOS 按钮)
    PhotoMedicine.vue     # 拍照问药 (含摄像头实时预览)
    FamilyHome.vue        # 手机端首页
    HealthProfile.vue / MedicalRecord.vue / MedicationManager.vue / Reminder.vue
  composables/            # useWakeController 等
  utils/                  # voiceSession / wakeHandoff 等
backend/                  # 后端 (FastAPI)
  main.py  database.py  models.py  schemas.py  init_db.py
  routers/                # users / records / medications / dashboard / chat / device / garmin
  services/
    local_camera.py       # 摄像头拍照 + CameraStream 实时流 (MJPEG)
    local_kws.py          # 本地唤醒 (Sherpa)
    local_asr.py          # 本地语音识别 (Sherpa)
    local_audio.py        # 录音 (arecord)
    wake_service.py       # 唤醒会话调度
    cloud_llm_service.py / cloud_tts_service.py / chat_service.py
    rag_service.py        # FAISS 知识检索
    reminder_service.py   # 用药提醒调度
    notify_service.py     # 每日日报 / SOS 微信推送 (Server 酱)
    garmin_service.py     # 佳明手表数据
rag/                      # 知识库 (disease / medicine / emergency / elderly)
scripts/                  # 启动脚本 + 边缘 AI benchmark
docs/                     # 项目文档
```

## 6. 快速开始

### 后端（FastAPI）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # 板端用 requirements-board.txt

cp .env.example .env                      # 填入 DASHSCOPE_API_KEY 等
python -m backend.init_db                 # 初始化数据库
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端（Vue3）

```bash
npm install
npm run dev                               # http://<板子IP>:5173
```

### 板端一键启动（RK3588）

```bash
sudo apt install -y fswebcam alsa-utils python3-pip
pip install -r requirements-board.txt
bash scripts/start-board.sh               # 拉起后端 + 前端 + 本地模型
```

## 7. 环境变量

复制 `.env.example` 为 `.env` 后按需修改（**切勿把真实密钥提交到仓库**）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | - | **必须**，DashScope API Key |
| `DASHSCOPE_MODEL` | `qwen-turbo` | 云端文本对话模型 |
| `DASHSCOPE_VISION_MODEL` | `qwen-vl-max` | 云端视觉模型（拍照问药） |
| `CHAT_USE_CLOUD_LLM` | `1` | 1=问诊走云端，0=走板端本地 LLM |
| `TTS_USE_CLOUD` | `1` | 1=CosyVoice 云端 TTS，0=Piper 本地 TTS |
| `COSYVOICE_VOICE` | `longanyang` | 云端 TTS 音色 |
| `CAMERA_DEVICE_INDEX` | `11` | 摄像头设备号（`/dev/video11`） |
| `WAKE_ENABLED` | `1` | 是否启用唤醒 |
| `KWS_KEYWORDS_SCORE` / `KWS_KEYWORDS_THRESHOLD` / `KWS_RMS_GATE` | `4.5` / `0.25` / `80` | 唤醒灵敏度与防误触发门控 |
| `SERVERCHAN_KEY` | - | Server 酱 Key（SOS / 日报微信推送） |
| `REMINDER_ENABLED` | `1` | 是否启用用药提醒调度 |

## 8. 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dashboard/stats` | 健康大屏统计 |
| POST | `/chat` | 文字问诊（LLM + RAG） |
| GET | `/device/camera/stream` | 摄像头 MJPEG 实时流 |
| POST | `/device/camera/capture` | 拍照（实时流运行时直接截帧） |
| POST | `/device/listen` | 录音 + 本地 ASR |
| POST | `/device/speak` | TTS 播报 |
| POST | `/device/sos` | SOS 紧急求助（微信推送） |
| GET/POST | `/device/reminders/*` | 用药提醒查询 / 确认 |
| GET | `/users`、`/records`、`/medications` | 档案 / 病例 / 药物管理 |

## 9. 边缘 AI 性能（Benchmark）

板端提供完整的边缘 AI 性能测试套件（KWS/ASR/RAG/LLM/TTS/全链路/系统资源）：

```bash
python scripts/run_all_benchmarks.py      # 生成 benchmark_report.md
```

RK3588 实测摘要（详见 [benchmark_report.md](benchmark_report.md)）：

| 能力 | 关键指标 |
|------|---------|
| KWS 唤醒 | 延迟 ≈ 560 ms，误唤醒率 0%，峰值内存 95 MB |
| ASR 识别 | RTF ≈ 0.04，中文 CER ≈ 7.7% |
| RAG 检索 | 平均 68 ms，Top3 命中率 90% |
| 本地 TTS (Piper) | 合成 ≈ 1.06 s，RTF ≈ 0.42 |
| 系统资源 | CPU 峰值 70.8%，内存峰值 6.0 GB，温度峰值 84°C |

## License

MIT
