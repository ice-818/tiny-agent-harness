# Tiny Agent Harness (轻量级企业级Agent运行底座)

一个从零手搓的轻量级 Agent Harness（智能体外壳）基础设施。拒绝纯黑盒框架，专注于企业级的高可用、安全隔离、状态容错与可观测性。

## ✨ 核心设计

- **模型路由层 (Model Router)**：拒绝单一的模型绑定。基于能力路由（Chat / Reasoner / Vision），实现本地大模型（Ollama）与云端大模型（阿里云API）的智能分流与降级。
- **状态持久化 (State & Checkpoint)**：借鉴企业级架构的Outbox模式与分布式锁，实现任务的断点续传与防双跑。
- **安全护栏 (Guardrail)**：基于YAML配置的白名单机制，实施API面收窄，拒绝高危工具执行。
- **多租户隔离 (Tenant Context)**：声明式租户隔离，在框架层自动注入 `tenant_id`，杜绝跨租户越权。
- **可观测性 (Observability)**：基于 OTel 语义的异步埋点，记录每次调用耗时、Token消耗与成功率。
- **混合RAG (RAG Engine)**：支持语义分块（Semantic Chunking）、混合检索与 RRF/MMR 重排算法。

## 🚀 快速开始

1. 安装依赖：`pip install -r requirements.txt`
2. 配置环境变量：参考 `.env.example`（请自行创建真实 `.env` 并填入API Key）
3. 运行模型路由测试：`python main.py`

## 📁 目录结构

- `main.py`：测试入口
- `router.py`：模型能力路由
- `test_local.py` / `test_cloud.py`：本地/云端模型连通性测试
- `.gitignore`：工程安全规范（保护 `.env` 凭证与虚拟环境）

> 本项目架构灵感源于对企业级AI原生平台底层设计（编排、容错、沙箱、多租户、可观测性）的深度调研与降维复刻。
