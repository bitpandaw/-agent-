# 原有数据流到分布式架构的映射

## 一、当前单体数据流

### 1.1 主流程

```
用户输入 (stdin)
       │
       ▼
  entry.main()
       │
       ├── initialize_runtime()  →  context
       │      • OpenAI client (DeepSeek)
       │      • ChromaDB collection
       │      • embedding_model (SentenceTransformer)
       │      • conversation (list)
       │      • tool_registry
       │
       ├── load_and_chunk_document()  →  chunks
       ├── index_documents(chunks)    →  写入 ChromaDB
       │
       └── run_turn(user_input, context, session_state)
                    │
                    ▼
  orchestrator.run_orchestrator()
       │
       └── 循环 (max_steps=10):
              ├── plan_actions()  →  planner 调 LLM
              │      • 有 tool_calls → 返回 actions[]
              │      • 无 tool_calls → 追加 assistant 回复，break
              │
              ├── execute_actions(actions)
              │      └── 遍历 tool_registry[tool_name](args, context)
              │
              └── 将 tool 结果追加到 conversation
```

### 1.2 工具调用链

```
executor.execute_actions()
       │
       ├── search_knowledge
       │      └── rag.retrieve_context(query, context, top_k, score_threshold)
       │             ├── embedding_model.encode(query)
       │             └── collection.query()
       │
       ├── calculator
       │      └── eval(expression)  [纯本地]
       │
       └── query_fault_history
              └── sqlite3.connect(db_path).execute(SQL)
```

### 1.3 数据依赖


| 组件            | 依赖                                                      |
| ------------- | ------------------------------------------------------- |
| entry         | config, OpenAI, ChromaDB, embedding_model, rag_pipeline |
| orchestrator  | planner, executor, context                              |
| planner       | OpenAI client, conversation, TOOLS_LIST                 |
| executor      | tool_registry, context                                  |
| tool_registry | rag.retrieve_context, config, sqlite3                   |
| rag_pipeline  | embedding_model, collection                             |


### 1.4 外部资源


| 资源                      | 类型      |
| ----------------------- | ------- |
| DeepSeek API            | 远程 HTTP |
| ChromaDB                | 本地      |
| SQLite                  | 本地文件    |
| equipment_knowledge.txt | 本地文件    |
| SentenceTransformer     | 本地模型    |


---

## 二、分布式服务划分

### 2.1 API 层拆分为四个模块


| 模块               | 职责                                     | 原模块                      | 端口   |
| ---------------- | -------------------------------------- | ------------------------ | ---- |
| **Gateway**      | HTTP 入口、会话管理、接收 /chat、转发请求             | entry                    | 8000 |
| **Orchestrator** | 编排循环、协调 Plan 与 Execute、维护 conversation | orchestrator             | 8001 |
| **Planner**      | 调 LLM 规划、解析 tool_calls、返回 actions      | planner                  | 8002 |
| **Executor**     | 执行工具、分发到 RAG/calculator/DB、汇总结果        | executor + tool_registry | 8003 |


### 2.2 其他服务


| 服务             | 职责       | 原模块                         | 端口   |
| -------------- | -------- | --------------------------- | ---- |
| RAG            | 分块、索引、检索 | rag_pipeline                | 8010 |
| Embedding (可选) | 文本向量化    | get_embedding_model, encode | 8011 |
| ChromaDB       | 向量存储     | chromadb                    | 8012 |


---

## 三、调用方式变化


| 原调用                                  | 分布式后                                      |
| ------------------------------------ | ----------------------------------------- |
| `entry.run_turn()`                   | Gateway → HTTP → Orchestrator `/turn`     |
| `orchestrator` 调 `plan_actions()`    | Orchestrator → HTTP → Planner `/plan`     |
| `orchestrator` 调 `execute_actions()` | Orchestrator → HTTP → Executor `/execute` |
| `retrieve_context(...)`              | Executor → HTTP → RAG `/retrieve`         |
| `embedding_model.encode(text)`       | 可选：RAG → HTTP → Embedding `/embed`        |
| `client.chat.completions.create()`   | Planner 直接调 DeepSeek                      |
| `calculator`, `query_fault_history`  | 留在 Executor 内                             |


---

## 四、分布式数据流

```
HTTP POST /chat
       │
       ▼
┌─────────────────────────────────────┐
│ Gateway :8000                       │
│ • 接收 message, session_id          │
│ • 查/建会话，转发到 Orchestrator    │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│ Orchestrator :8001                  │
│ • 循环: 调用 Planner → 若有 actions 则调用 Executor
│ • 维护 conversation，直到无 tool_calls
└─────────────────────────────────────┘
       │
       ├──────────────────────────────────┐
       ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│ Planner :8002       │          │ Executor :8003      │
│ • 调 LLM (DeepSeek) │          │ • search_knowledge  │
│ • 解析 tool_calls   │          │   → HTTP → RAG      │
│ • 返回 actions[]    │          │ • calculator (本地) │
└─────────────────────┘          │ • query_fault_history│
                                 │   (本地 SQLite)     │
                                 └─────────────────────┘
                                          │
                                          │ search_knowledge
                                          ▼
                                 ┌─────────────────────┐
                                 │ RAG :8010           │
                                 │ POST /retrieve      │
                                 │ • ChromaDB          │
                                 │ • 可选: Embedding   │
                                 └─────────────────────┘
```

---

## 五、模块映射表


| 原模块/函数                                               | 分布式归属                 | 通信                  |
| ---------------------------------------------------- | --------------------- | ------------------- |
| entry.main, entry.initialize_runtime, entry.run_turn | Gateway               | -                   |
| orchestrator.run_orchestrator                        | Orchestrator          | 调用 Planner、Executor |
| planner.plan_actions, planner.build_turn_input       | Planner               | 调用 DeepSeek         |
| executor.execute_actions                             | Executor              | -                   |
| tool_registry.search_knowledge                       | Executor 调用方 + RAG 实现 | HTTP → RAG          |
| tool_registry.calculator                             | Executor              | -                   |
| tool_registry.query_fault_history                    | Executor              | -                   |
| rag.*                                                | RAG                   | -                   |
| get_embedding_model                                  | RAG 或 Embedding       | -                   |


---

## 六、Runtime / Session / TurnContext 解耦设计

### 6.1 概念定义


| 概念              | 本质      | 存放内容                                                       | 归属            |
| --------------- | ------- | ---------------------------------------------------------- | ------------- |
| **Runtime**     | 共享运行时   | client, config, collection, embedding_model, tool_registry | 进程级，启动时创建一次   |
| **Session**     | 会话状态    | session_state, messages, lock                              | 每会话独立一份       |
| **messages**    | 对话历史    | [system, user, assistant, tool, ...]                       | 每会话一份         |
| **TurnContext** | 单次请求上下文 | Runtime + messages                                         | 每次请求临时组装，用完即弃 |


### 6.2 解耦原则

- **Runtime 无会话**：不含 session_id、conversation
- **Session 无基础设施**：不含 client、collection 等
- **TurnContext 临时**：不持久化，每次请求组装

### 6.3 数据流

```
启动: runtime = init_runtime()   # 不含 conversation

创建 Session:
  session = {
      session_state: {...},
      messages: [system_prompt],
      lock: Lock()
  }

每次 /chat:
  session = store.get_or_create(session_id)
  turn_context = {**runtime, "conversation": session["messages"]}
  turn_result = run_turn(message, turn_context, session["session_state"])
  # run_turn 内部 append 到 turn_context["conversation"]，
  # 即 session["messages"]（同一引用），自动更新
```

### 6.4 原 context 与归属


| 原 context 键     | 归属               | 说明              |
| --------------- | ---------------- | --------------- |
| client          | Runtime          | Planner 用       |
| config          | Runtime          | 各服务环境变量         |
| collection      | Runtime          | RAG 用           |
| tool_registry   | Runtime          | Executor 用      |
| embedding_model | Runtime          | RAG 或 Embedding |
| conversation    | Session.messages | 每会话独立           |


---

## 七、接口契约

### Gateway (对外)

- **GET /health**: `{"status": "ok"}`
- **POST /chat**
  - Request: `{"message": str, "session_id": str?}`
  - Response: `{"reply": str, "turn_id": int}`

### Orchestrator（内部）

- **POST /turn**
  - Request: `{"user_input": str, "conversation": [...], "session_id": str, "turn_id": int}`
  - Response: `{"assistant_output": str, "tool_events": [...]}`

### Planner（内部）

- **POST /plan**
  - Request: `{"conversation": [...]}`
  - Response: `{"actions": [...], "has_tool_calls": bool}`

### Executor（内部）

- **POST /execute**
  - Request: `{"actions": [...], "context": {...}}`
  - Response: `{"tool_events": [...]}`

### RAG

- **POST /retrieve**
  - Request: `{"query": str, "top_k": int, "score_threshold": float}`
  - Response: `{"results": [{"doc_id", "text", "score"}]}`

### Embedding

- **POST /embed**
  - Request: `{"texts": [str]}`
  - Response: `{"vectors": [[float]]}`

### 7.1 HTTP 状态码与业务码体系

REST 化后有两层语义，可并存：


| 层级           | 用途               | 示例                                              |
| ------------ | ---------------- | ----------------------------------------------- |
| **HTTP 状态码** | 协议层：请求是否送达、是否被处理 | 200 成功，400 参数错误，500 服务异常                        |
| **业务码**      | 应用层：业务成功/失败及原因   | `ok`, `code`（S_xxx/E_xxx）, `message`, `payload` |


业务码沿用 ARCHITECTURE 中的 ToolResult 结构，详见 `ARCHITECTURE.md` 4.3 节。分布式后：

- HTTP 状态码由框架/协议决定（如 FastAPI 默认 200/422/500）
- 响应体可携带 `{ok, code, message, payload}`，与单体时 tool_registry 的 ToolResult 对齐
- 内部服务（RAG、Embedding）若需统一错误语义，可在响应体中采用 ToolResult 格式；简单接口（如仅返回 vectors）可仅返回数据，由调用方包装

---

## 八、部署拓扑

```
                    用户
                      │
                      ▼
              ┌─────────────┐
              │ Gateway     │
              │ :8000       │
              └──────┬──────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │Orchestr. │ │ Planner  │ │ Executor │
    │ :8001    │ │ :8002    │ │ :8003    │
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         │            │            │
         │            │            │  search_knowledge
         │            │            ▼
         │            │      ┌──────────┐
         │            │      │ RAG      │
         │            │      │ :8010    │
         │            │      └────┬─────┘
         │            │           │
         │            │      ┌────┴────┐
         │            │      │ChromaDB │
         │            │      └─────────┘
         │            │
         │            ▼
         │      DeepSeek (外网)
```

---

## 九、实施顺序

1. **Gateway**：FastAPI + `/chat`，内部仍直接调 `run_orchestrator`（不拆）
2. **RAG 服务**：独立服务，Executor 的 search_knowledge 改为 HTTP 调用
3. **四模块拆分**：Gateway → Orchestrator → Planner / Executor（Orchestrator 通过 HTTP 调 Planner、Executor）
4. **Docker**：各模块 Dockerfile + docker-compose
5. 可选：Embedding 独立、PostgreSQL 替代 SQLite

