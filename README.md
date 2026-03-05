# HotpotQA 多跳问答 Agent 系统

基于 **RAG + ReAct** 架构的维基百科多跳问答系统，使用 HotpotQA 数据集。自研编排框架（未使用 LangChain），支持知识检索（RAG）、历史问答查询（SQL）、文章图谱多跳推理（Neo4j）、数学计算四种工具。

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
          │search_knowledge│  │  calculator   │  │query_qa_records│
          │  (RAG 检索)    │  │  (数学计算)   │  │search_article_ │
          └───────┬───────┘  └───────────────┘  │  graph (KG)    │
                  │                             └────┬─────┬─────┘
          ┌───────▼───────┐                   ┌──────▼─┐ ┌▼──────┐
          │   ChromaDB    │                   │ SQLite │ │ Neo4j │
          │ + MiniLM 向量 │                   │qa_records│ │Article│
          └───────────────┘                   └────────┘ └───────┘
```

**单轮数据流：** 用户消息 → Gateway 路由到会话 → Orchestrator 启动 ReAct 循环 → Planner 调用 DeepSeek 生成工具调用 → Executor 分发执行 → 工具结果回填对话 → 循环直到 LLM 输出最终回答。

## 技术栈

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| LLM | DeepSeek | 支持 function calling，成本低 |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 | 多语言支持，适配 HotpotQA 英文 |
| 向量数据库 | ChromaDB | 轻量、内嵌，适合原型与单机部署 |
| 结构化存储 | SQLite | 零配置，qa_records 历史问答 |
| API 框架 | FastAPI | 异步高性能，自动生成 OpenAPI 文档 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 API Key
export DEEPSEEK_API_KEY="your-key-here"

# 3. 初始化数据库（qa_records）
python init_db.py

# 4. 启动服务（按顺序）
# ① Embedding 服务（8011，必须先起）
uvicorn embedding.embedding:app --host 0.0.0.0 --port 8011

# ② RAG 服务（8010），依赖 embedding
uvicorn rag.rag_pipeline:app --host 0.0.0.0 --port 8010

# ③ Gateway（8000）
uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000
```

## API

```bash
# 健康检查
curl http://localhost:8000/health

# 对话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "In what year was Moscow State University founded?", "session_id": "s1"}'
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
- **独立 Embedding 服务**：RAG 索引与检索均通过 `http://localhost:8011/embed` 调用，不加载本地模型。本地调试时须先启动 embedding（8011），再启动 RAG（8010）。
