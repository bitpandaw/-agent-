# 工业设备故障诊断 Agent 系统

基于 **RAG + ReAct** 架构的工业设备智能故障诊断系统，面向 SINUMERIK 808D 数控机床。自研编排框架（未使用 LangChain），支持知识检索、数学计算、故障历史查询三种工具的多轮推理。

## 架构

```
                         POST /chat
                             │
                      ┌──────▼──────┐
                      │   Gateway   │  FastAPI + SessionStore
                      └──────┬──────┘
                             │
                      ┌──────▼──────┐
                      │ Orchestrator│  ReAct 循环（最多 10 步）
                      └──┬──────┬───┘
                         │      │
              ┌──────────▼┐    ┌▼───────────┐
              │  Planner  │    │  Executor   │
              │ (DeepSeek)│    │ (工具分发)  │
              └───────────┘    └──┬───┬───┬──┘
                                  │   │   │
                  ┌───────────────┘   │   └───────────────┐
                  │                   │                   │
          ┌───────▼───────┐  ┌───────▼───────┐  ┌────────▼───────┐
          │search_knowledge│  │  calculator   │  │query_fault_    │
          │  (RAG 检索)    │  │  (数学计算)   │  │   history       │
          └───────┬───────┘  └───────────────┘  └────────┬───────┘
                  │                                      │
          ┌───────▼───────┐                     ┌────────▼───────┐
          │   ChromaDB    │                     │    SQLite      │
          │ + MiniLM 向量 │                     │  故障历史记录  │
          └───────────────┘                     └────────────────┘
```

**单轮数据流：** 用户消息 → Gateway 路由到会话 → Orchestrator 启动 ReAct 循环 → Planner 调用 DeepSeek 生成工具调用 → Executor 分发执行 → 工具结果回填对话 → 循环直到 LLM 输出最终回答。

## 技术栈

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| LLM | DeepSeek | 支持 function calling，成本低 |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 | 多语言支持，适配中文工业文档 |
| 向量数据库 | ChromaDB | 轻量、内嵌，适合原型与单机部署 |
| 结构化存储 | SQLite | 零配置，故障历史查询 |
| API 框架 | FastAPI | 异步高性能，自动生成 OpenAPI 文档 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 API Key
export DEEPSEEK_API_KEY="your-key-here"

# 3. 初始化故障历史数据库
python init_db.py

# 4. 启动服务
uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000
```

## API

```bash
# 健康检查
curl http://localhost:8000/health

# 对话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "808D报警号700015是什么含义？", "session_id": "s1"}'
```

**请求/响应格式：**

```json
// Request
{"message": "string", "session_id": "string (可选，自动生成)"}

// Response
{"reply": "string", "session_id": "string", "turn_id": 1}
```

## 项目结构

```
├── gateway/           # FastAPI 入口 + 会话管理
├── orchestrator/      # ReAct 循环编排
├── planner/           # LLM 调用 + tool_calls 解析
├── executor/          # 工具分发执行
├── tools/             # 工具实现 + OpenAI function schema
├── rag/               # 分块、索引、检索（min-max 归一化）
├── embedding/         # Embedding 微服务
├── config/            # 统一配置（config.yaml）
├── state/             # 会话状态日志
└── knowledge_graph/   # 知识图谱构建（开发中）
```

## 设计决策

- **自研编排而非 LangChain**：保持对 ReAct 循环、工具调用、对话管理的完全控制，便于调试和定制。
- **min-max 归一化**：ChromaDB 返回的原始距离因 metric 不同尺度各异，归一化后统一到 [0, 1] 区间，使 `score_threshold` 配置在不同 distance metric 下通用。候选池扩大到 `3×top_k` 避免末位归一化恒为 0。
- **工具统一契约**：所有工具返回 `{ok, code, message, payload, latency_ms}` 结构，Executor 无需关心具体工具实现。
- **模块化微服务预备**：RAG 和 Embedding 已抽为独立 FastAPI 服务，可按需 Docker 部署。
