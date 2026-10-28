# Tiny Agent Harness

一个从零搭建、可读可改的 Python Agent 运行底座。V1.0 重点不是堆功能，而是把一次工具调用从「能跑」做到「遇到重试、进程重启和存储故障时仍不会悄悄重复执行」。

## V1.0 已交付

- 模型路由：本地 Ollama 聊天模型与 DashScope-compatible 推理模型。
- Agent Loop：工具调用、最大步数、可恢复 checkpoint、重试与结构化日志。
- 工具运行器：YAML 护栏、JSON Schema 参数校验、统一观察结果。
- Checkpoint：Redis CAS 主存储；Redis 不可用时自动落盘到本地 JSON。
- 持久化幂等：工具调用先被原子预留，再执行；重启后已完成调用回放结果而不再执行。
- 明确的异常语义：冲突返回 `idempotency conflict`；无法确认外部副作用时进入 `UNKNOWN`，停止并等待人工核对。
- FastAPI：启动、查看和恢复 run 的 HTTP 接口；离线端到端演示与完整测试。

## 快速验收（Windows PowerShell）

```powershell
cd D:\code\tiny-agent-harness
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python demo_e2e.py
```

`demo_e2e.py` 不会调用真实模型、Redis 或云端密钥；它会实际走一遍 HTTP API、Agent Loop、护栏、计算器工具和 checkpoint。

## 启动 API

先复制环境变量示例并按需要填写：

```powershell
Copy-Item .env.example .env
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000/docs` 使用交互式接口，或在另一个 PowerShell 中调用：

```powershell
$body = @{
  task = "请使用 calculator 工具计算 25 乘以 8"
  max_steps = 5
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/runs `
  -Method Post -ContentType "application/json" -Body $body
```

返回值含 `run_id`。在模型或进程中断后，可恢复尚未完成的 run：

```powershell
$resume = @{ max_steps = 5 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/runs/<run_id>/resume `
  -Method Post -ContentType "application/json" -Body $resume
```

查询 checkpoint 状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/runs/<run_id>
```

## 工具调用恢复语义

| 记录状态 | 系统行为 | 是否自动重试 |
| --- | --- | --- |
| `COMPLETED` | 回放已保存的工具观察结果，并继续下一轮 | 否，不会重复执行 |
| `IN_PROGRESS` | 返回“稍后重试”，避免并发 worker 双跑 | 否 |
| `UNKNOWN` | run 变为 `needs_manual_reconciliation` | **绝不自动重试** |

`UNKNOWN` 代表调用边界外可能已经产生副作用、但进程无法确认结果。例如向支付或订单系统发送请求后网络断开。此时应先在外部系统按业务 ID 核对，再决定是否补偿或重试。

## 存储与配置

`.env.example` 中的配置：

- `TINY_AGENT_REDIS_HOST` / `PORT` / `DB`：Redis 为 checkpoint 和幂等记录的主存储。
- `TINY_AGENT_DATA_DIR`：Redis 不可用时本地 JSON 的持久化目录，默认 `data/`。
- `DASHSCOPE_API_KEY`：仅云端推理模型需要。默认聊天路由使用本地 Ollama。

生产部署、TLS、备份、安全边界与限制请见 [部署说明](docs/deployment.md)。

## 兼容性

原有 `run(task, max_steps=5, run_id=None)` 调用仍可用，传入 `run_id` 时仍按恢复语义处理。新增的 `resume=False` 只供 API 在指定新 `run_id` 时显式创建任务使用。原有 in-process `IdempotencyManager` 也保留；Agent Loop 在 V1.0 默认使用 `PersistentIdempotencyManager`。

## 建议学习顺序

1. 从 `tools_pkg/executor.py` 看护栏、Schema 校验和统一工具结果。
2. 阅读 `core/loop.py`，对照一次正常工具调用与 checkpoint 保存顺序。
3. 阅读 `core/idempotency.py` 中 `COMPLETED / IN_PROGRESS / UNKNOWN` 的状态机。
4. 运行 `demo_e2e.py`，再阅读对应测试：`tests/test_api.py`、`tests/test_persistent_idempotency.py`、`tests/test_loop_v1_recovery.py`。
5. 最后接入真实模型与 Redis，并用 `/docs` 操作一次完整 run 与恢复。
