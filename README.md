# 工业设备故障诊断 RAG Agent

面向工业设备的故障诊断智能问答系统，结合 RAG（ChromaDB + SentenceTransformer）、知识图谱（Neo4j）和 Reranker（CrossEncoder），通过 Function Calling 实现多步检索与推理。**HotpotQA 仅用于验证与测试**（多跳推理能力、检索质量评估），实际场景可切换为工业知识库。

## 技术栈

- **RAG**：ChromaDB、SentenceTransformer、min-max 归一化
- **Reranker**：cross-encoder/ms-marco-MiniLM-L-12-v2
- **LLM**：DeepSeek
- **知识图谱**：Neo4j
- **Web**：FastAPI
- 自研架构，未使用 LangChain

## 项目结构

| 模块 | 职责 |
|------|------|
| `gateway` | FastAPI 入口，`/chat`、SessionStore |
| `orchestrator` | 多步工具调用循环，调 planner + executor |
| `planner` | 调用 LLM，解析 tool_calls |
| `executor` | 执行 TOOL_REGISTRY 中的工具 |
| `tools` | search_knowledge、calculator、query_qa_records、search_article_graph |
| `rag` | 分块、索引、检索、Reranker、KG 融合 |
| `embedding` | 向量化服务（独立进程） |
| `knowledge_graph` | 构建 structured_articles 与 Neo4j 图谱（测试阶段从 HotpotQA 生成） |

## 环境要求

- Python 3.10+
- 环境变量：`DEEPSEEK_API_KEY`（必需）
- 可选：`REDIS_URL`（会话存储）

```bash
pip install -r requirements.txt
```

## 运行模式

| 模式 | 说明 | 配置 |
|------|------|------|
| **single_process** | 单进程：仅启动 Gateway，RAG/Embedding 在进程内执行 | `run_mode: "single_process"`（默认） |
| **distributed** | 微服务：Embedding(8011)、RAG(8010)、Gateway(8000) 分别启动 | `run_mode: "distributed"` |

## 服务与端口

| 端口 | 服务 | 命令 | 依赖 |
|------|------|------|------|
| 8000 | Gateway | `uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000` | 单进程下无额外依赖 |
| 8011 | Embedding | `uvicorn embedding.embedding:app --host 0.0.0.0 --port 8011` | 仅 distributed 需要 |
| 8010 | RAG | `uvicorn rag.rag_pipeline:app --host 0.0.0.0 --port 8010` | 仅 distributed 需要 |
| 7687 | Neo4j | `docker-compose up -d` | 可选（KG 检索需要） |

**单进程模式（推荐）**：只启动 Gateway，Embedding、ChromaDB、Reranker、KG 均在进程内加载。

## 手动启动（推荐）

**单进程**（`config.run_mode: single_process`）：

```powershell
python -m uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000
```

**微服务**（`config.run_mode: distributed`）：

```powershell
# 终端 1：Embedding（必须先启动）
python -m uvicorn embedding.embedding:app --host 0.0.0.0 --port 8011

# 终端 2：RAG
python -m uvicorn rag.rag_pipeline:app --host 0.0.0.0 --port 8010

# 终端 3：Gateway
python -m uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000
```

Neo4j（可选，用于 rag_kg_reranker）：

```powershell
docker-compose up -d
```

## 一键启动（Windows）

```powershell
# 单进程（默认，仅启动 Gateway）
.\start\start_services.ps1

# 微服务（Embedding + RAG + Gateway）
.\start\start_services.ps1 -Distributed

# 跳过 Neo4j
.\start\start_services.ps1 -SkipDocker
```

## 初始化

```bash
# 初始化 qa_records 数据库（测试用：优先从 hotpotqa_db_seed.json，否则从 HotpotQA 采样）
python init_db.py
```

## 知识图谱（可选）

测试阶段使用 HotpotQA 生成图谱：

```bash
# 1. 从 HotpotQA 生成 structured_articles.json（仅测试用）
python knowledge_graph/build_hotpot_articles.py

# 2. 安装 spaCy 英文模型
pip install spacy && python -m spacy download en_core_web_sm

# 3. 确保 Neo4j 已启动，导入图谱
python knowledge_graph/build_graph.py
```

## API 使用

### 健康检查

```bash
curl http://localhost:8000/health
curl http://localhost:8011/health
curl http://localhost:8010/reranker_status
```

### 对话

```bash
# 测试用示例（HotpotQA 风格问题）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "In what year was Moscow State University founded?", "session_id": "test-1"}'
```

### RAG 检索（直接调用）

```bash
curl -X POST http://localhost:8010/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "Moscow State University", "use_reranker": true, "use_kg": true}'
```

## 实验：RAG+Reranker vs RAG+KG+Reranker

对比 `rag_reranker` 与 `rag_kg_reranker` 的检索质量（hit@k、recall@k、precision@k、mrr、ndcg、map、coverage）。

**前置条件**：Embedding(8011)、RAG(8010) 已启动；跑 `rag_kg_reranker` 时需 Neo4j 已启动并导入图谱。

```bash
# 默认 50 样本，8 workers
python experiments/run_reranker_experiment.py

# 自定义
python experiments/run_reranker_experiment.py --max-samples 100 --workers 16
python experiments/run_reranker_experiment.py --variant rag_reranker  # 仅跑单一变体
```

结果输出到 `experiments/results/reranker_summary.json`。

## 配置

主配置在 `config/config.yaml`：

- `run_mode`：`single_process`（单进程，默认）或 `distributed`（微服务）
- `rag.top_k`：检索返回数量（默认 30）
- `rag.use_kg`：是否默认启用 KG 检索
- `reranker.enabled`：是否启用 Reranker
- `paths.knowledge_file`：知识库文件（测试用 `data/hotpot_knowledge.txt`，工业场景可替换）
- `neo4j`：Neo4j 连接信息

## 数据契约

- **PlanAction**：`{tool_name, tool_args, tool_call_id}`
- **ToolResult**：`{ok, code, message, payload, latency_ms, tool_name}`
- **ChatRequest/ChatResponse**：`{message, session_id}` / `{reply, session_id, turn_id}`
