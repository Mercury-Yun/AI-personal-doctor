# AI私人医生（AI Personal Doctor）

云端化 AI 私人医生项目（DashScope 通义千问 + 本地摄像头/麦克风）。

## 技术栈

- Frontend: Vue3 + Vite + Vue Router + Pinia + Element Plus
- Backend: FastAPI + SQLAlchemy
- Database: SQLite
- Chart: ECharts
- RAG: FAISS + sentence-transformers + BAAI/bge-small-zh-v1.5
- LLM / VLM / TTS: DashScope（Qwen-Turbo / Qwen-VL-Max / CosyVoice）
- 本地硬件: OpenCV / fswebcam（拍照）、arecord（录音）

## 功能范围

- Dashboard 首页：Apple Health 风格医疗 Dashboard，展示真实统计数据、健康画像和 ECharts 趋势图。
- 健康档案管理：新增、编辑、查看、删除，数据写入 SQLite。
- 病例管理：手动录入病例，支持新增、编辑、删除、查看详情。
- 药物管理：维护药物名称、剂量、频率、服用时间和备注，支持按患者筛选。
- 用药提醒：按服用时间排序展示今日药物，到点弹出浏览器提醒（TTS 播报）。
- 问诊：支持患者选择、会话列表、多轮聊天历史保存、患者上下文注入、RAG知识库检索、云端 LLM 回答。
- 拍照问药：本地摄像头拍照 → DashScope VLM 视觉理解 → 回答药名、用法、注意事项，支持追问和「换一个」。
- RAG知识库：启动时扫描 `rag/`，生成Embedding并建立FAISS索引。
- REST API：提供 `/users`、`/records`、`/medications`、`/dashboard/stats`、`/device/*` 等接口。

## 项目结构

```text
src/
  api/
  assets/
  router/
  store/
  views/
    Dashboard.vue
    DoctorChat.vue
    PhotoMedicine.vue
    HealthProfile.vue
    MedicalRecord.vue
    MedicationManager.vue
    Reminder.vue
  App.vue
  main.js
backend/
  main.py
  database.py
  models.py
  schemas.py
  init_db.py
  init.sql
  routers/
    users.py
    records.py
    medications.py
    dashboard.py
    chat.py
    device.py
  services/
    local_camera.py
    local_audio.py
    cloud_llm_service.py
    cloud_tts_service.py
    rag_service.py
    chat_service.py
    wake_service.py
    reminder_service.py
rag/
  disease/
  medicine/
  emergency/
  elderly/
```

## 后端运行（云端化版本）

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python -m backend.init_db

# 启动 FastAPI（无需 demo）
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

## 板端部署（RK3588）

1. 安装系统依赖：
   ```bash
   sudo apt update
   sudo apt install -y fswebcam alsa-utils python3-pip
   ```

2. 克隆代码并安装 Python 依赖：
   ```bash
   git clone <your-repo> AI-Personal-Doctor
   cd AI-Personal-Doctor
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-board.txt
   ```

3. 配置 `.env`（必须）：
   ```env
   DASHSCOPE_API_KEY=sk-xxx
   ```

4. 启动：
   ```bash
   bash scripts/start-board.sh
   ```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | - | **必须**，DashScope API Key |
| `DASHSCOPE_MODEL` | `qwen-turbo` | 文本对话模型 |
| `DASHSCOPE_VISION_MODEL` | `qwen-vl-max` | 视觉理解模型（拍照问药） |
| `COSYVOICE_VOICE` | `longanyang` | TTS 音色 |
| `WAKE_ENABLED` | `1` | 是否启用唤醒功能 |
| `VOICE_WAKE_WORD` | `豆包` | 唤醒词（前端按钮触发） |

## 开发说明

- 本地拍照：`backend/services/local_camera.py`（OpenCV 优先，fswebcam 回退）
- 本地录音：`backend/services/local_audio.py`（arecord）
- 所有重计算（ASR / VLM / TTS / LLM）均通过 DashScope 云端 API 完成
- 主要延迟来源为云端调用（VLM 3~12s，ASR 1.5~4s，TTS 1~3s）

## License

MIT
