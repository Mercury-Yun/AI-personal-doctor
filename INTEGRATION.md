# AI 私人医生 × Qwen Demo 整合指南（第一阶段）

本阶段目标：**健康屏（Vue + FastAPI）与 RK3588 语音 demo 联通**，实现到点用药 TTS 提醒。

## 架构

```
Vue 大屏 (5173)
    ↓ /api
FastAPI (8000) ── reminder 调度 ──→ POST http://127.0.0.1:8765/speak
    ↓ SQLite                           ↑
档案/药物/提醒                          demo 控制口 (control_server)
                                       ↓
                                    TTS / 语音 / 识图
```

## 第一步：板端启动 demo

```bash
cd ~/Qwen_test   # install/demo_Linux_aarch64 拷贝目录
export DEMO_CONTROL_PORT=8765
export CAMERA_DEVICE_INDEX=11
./demo <encoder.rknn> <llm.rkllm> <max_tokens> <max_context>
```

启动后应看到日志：

```
control: HTTP server listening on http://127.0.0.1:8765
```

测试控制口：

```bash
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/speak -H 'Content-Type: application/json' \
  -d '{"text":"语音测试"}'
```

## 第二步：启动 FastAPI

```bash
cd ~/AI-Personal-Doctor
export DEMO_CONTROL_URL=http://127.0.0.1:8765
export REMINDER_ENABLED=1
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## 第三步：启动前端

```bash
cd ~/AI-Personal-Doctor
npm run dev
```

浏览器打开 `http://127.0.0.1:5173/device`，确认「语音引擎在线」。

## 第四步：配置用药提醒

1. 在 **健康档案** 添加患者
2. 在 **药物管理** 添加药物，设置 `take_time` 如 `08:00`
3. 打开 **用药提醒** 页面保持前台（或 Dashboard）
4. 到点后 FastAPI 会调用 demo TTS 播报，大屏同步弹窗

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEMO_CONTROL_URL` | `http://127.0.0.1:8765` | FastAPI → demo 控制地址 |
| `DEMO_CONTROL_PORT` | `8765` | demo 控制口端口 |
| `REMINDER_ENABLED` | `1` | 是否启用后端提醒调度 |
| `REMINDER_CHECK_INTERVAL_SEC` | `30` | 检查间隔（秒） |
| `REMINDER_REPEAT_MINUTES` | `5` | 未确认时重复播报间隔 |
| `CORS_ORIGINS` | - | 额外 CORS 来源，逗号分隔 |

## API（新增）

- `GET /device/status` — demo 是否在线
- `POST /device/speak` — `{ "text": "..." }` 触发 TTS
- `POST /device/voice/start` — 进入 demo 语音对话模式
- `POST /device/voice/stop` — 退出语音对话模式
- `GET /device/reminders/today` — 今日用药计划
- `POST /device/reminders/ack` — `{ "medication_id": 1 }` 标记已服

## 下一步（第二阶段预告）

- ~~demo 增加 `/voice/start`、`/voice/stop`~~（已完成）
- ~~FastAPI `/chat` 对接 Qwen 真 LLM + RAG~~（已完成，demo 离线时回退 mock）
- ~~语音问诊 `/chat/voice`~~（已完成：听 → 答 → 朗读，无需打字）
- 手机远程改档案（登录 + HTTPS）
- 板端一键启动：`bash scripts/launch-health-screen.sh`

### 问诊 API

- `POST /chat` — `{ "session_id", "user_id", "question" }` 文字问诊（接 Qwen）
- `POST /chat/voice` — `{ "session_id", "user_id", "speak": true }` 语音问诊（ASR + Qwen + TTS）

demo 控制口新增：

- `POST /chat` — `{ "prompt": "...", "speak": false }`
- `POST /listen` — 录音识别，返回 `{ "text": "..." }`

## PC 交叉编译 demo

```bash
cd deploy
./build-linux.sh
# 产物：install/demo_Linux_aarch64/demo
scp -r install/demo_Linux_aarch64/* board:~/Qwen_test/
```
