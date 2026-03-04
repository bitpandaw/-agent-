# 分布式架构设计文档

> 本文档记录将单进程 RAG Agent 系统改造为分布式多服务架构的设计决策。
> 职责边界与原模块设计保持一致，所有进程无状态，持久数据全部外置。

---

## 一、服务拓扑

```
[Client]
    │ HTTP
    ▼
[Gateway :8000]  ── 完全无状态，只做 HTTP 路由 + Redis 读写 + 分布式锁
    │ HTTP
    ▼
[Orchestrator :8001]  ── 无状态；每步从 Redis 读写 conversation；负责 system_prompt 注入
    ├── HTTP → [Planner :8002]     ── 无状态；调 DeepSeek LLM
    └── HTTP → [Executor :8003]    ── 持有 tool_registry（进程级函数引用）
                    ├── calculator（纯计算，无状态）
                    ├── query_fault_history → [PostgreSQL]
                    └── search_knowledge   → HTTP → [RAG Service :8004]
                                                      ├── embedding_model（startup 常驻内存）
                                                      └── ChromaDB collection（startup 常驻内存）

[Redis]      ── 所有 session 状态（conversation + session_state + 分布式锁）
[PostgreSQL] ── fault_history 业务数据（替换当前 SQLite）
```

---

## 二、各进程状态归属

| 进程 | 持有状态 | 生命周期 |
|------|---------|---------|
| Gateway | **无状态** | — |
| Orchestrator | 只读 config（system_prompt 来源） | 进程级，startup 加载 |
| Planner | **无状态** | — |
| Executor | tool_registry（函数引用字典） | 进程级，startup 注册 |
| RAG Service | embedding_model + ChromaDB collection | 进程级，startup 加载 |
| Redis | conversation + session_state（全部 session） | 外部持久化 |
| PostgreSQL | fault_history 业务数据 | 外部持久化 |

**设计原则：** 所有业务进程无状态。进程崩溃重启不丢任何 session 数据，可随意水平扩展。

---

## 三、Redis 数据结构

```
conv:{session_id}    → List   conversation 消息序列
                               RPUSH 追加，LRANGE 0 -1 读全量
                               每条消息为 JSON 序列化的 {role, content, ...}

state:{session_id}   → Hash   session 元数据
                               turn_count    : int
                               error_count   : int
                               create_at     : ISO timestamp
                               turn_logs     : JSON 序列化的 list

lock:{session_id}    → String 分布式锁
                               值为持有者随机 UUID，TTL 30s
```

---

## 四、并发控制设计

同一 session 的并发请求在 **Gateway 层串行化**，不同 session 完全并行互不影响。

### 分布式锁流程（Gateway 层执行）

```
Gateway 收到请求
  │
  ├─ SET lock:{session_id} {random_uuid} NX PX 30000
  │    成功 → 转发给 Orchestrator，等待响应
  │    失败 → 等待 1s 后重试，最多 3 次
  │            仍失败 → 返回 HTTP 409 Conflict
  │
  ├─ Orchestrator 返回结果
  │
  └─ 校验 GET lock:{session_id} == 自己的 uuid → DEL lock:{session_id}
     （value 校验防止误释放其他请求持有的锁）
```

| 参数 | 值 | 原因 |
|------|----|------|
| TTL | 30s | 防止进程崩溃后锁永不释放 |
| NX | 是 | 原子写，避免竞态 |
| Value | 随机 UUID | 只有持有者才能释放 |
| 失败策略 | 重试 3 次（间隔 1s），仍失败返回 409 | 对客户端友好 |

---

## 五、HTTP 接口契约

### 1. Client → Gateway

```
POST /chat
  Request:  { "message": str, "session_id": str? }
            session_id 缺省时 Gateway 生成新 UUID
  Response: { "reply": str, "session_id": str, "turn_id": int }

GET /health
  Response: { "status": "ok", "service": "gateway" }
```

### 2. Gateway → Orchestrator

Gateway 只传 session_id + message，turn_id 由 Orchestrator 从 Redis state 读取并自增。

```
POST /turn
  Request:  { "session_id": str, "message": str }
  Response: { "reply": str, "turn_id": int }
```

### 3. Orchestrator → Planner

Orchestrator 每步将完整 conversation（system_prompt 作为第一条消息）传给 Planner。
Planner 始终在 response 中带回本次 LLM 生成的 message，Orchestrator 无需再读 Redis。

```
POST /plan
  Request:  {
    "conversation": [ { "role": str, "content": str, ... } ]
  }
  Response: {
    "has_tool_calls": bool,
    "actions": [                            // has_tool_calls=true 时有值
      { "tool_name": str, "tool_args": {}, "tool_call_id": str }
    ],
    "message": {                            // 始终返回，携带本次 LLM 生成结果
      "role": "assistant",
      "content": str,
      "tool_calls": [...]                   // has_tool_calls=true 时有值
    }
  }
```

> **为什么 message 始终返回：** 避免 Orchestrator 在获取最终回复时再读一次 Redis，
> 消除 TOCTOU 竞态——Planner 直接返回确定性结果，与 Redis 状态无关。

### 4. Orchestrator → Executor

```
POST /execute
  Request:  {
    "session_id": str,
    "actions": [
      { "tool_name": str, "tool_args": {}, "tool_call_id": str }
    ]
  }
  Response: {
    "tool_events": [
      {
        "ok": bool,
        "code": str,
        "message": str,
        "payload": any,
        "latency_ms": int,
        "tool_name": str,
        "tool_call_id": str
      }
    ]
  }
```

### 5. Executor → RAG Service（search_knowledge 内部调用，对上层不可见）

```
POST /retrieve
  Request:  { "query": str, "top_k": int, "score_threshold": float }
  Response: { "results": [ { "content": str, "score": float } ] }
```

> `search_knowledge` 在 Executor 进程内仍是普通函数，函数体内部用 httpx 调用 RAG Service，
> tool_registry 结构不变，Executor 执行逻辑不变。

### 各服务统一健康检查格式

```
GET /health
  Response: { "status": "ok", "service": "<service-name>" }
```

---

## 六、Orchestrator ReAct 循环详细流程

```
turn 开始（收到 session_id + message）
  │
  ├─ LRANGE conv:{session_id} 0 -1
  │   └─ 若为空（新 session）→ RPUSH system_prompt 消息（从自身 config 读取）
  │
  ├─ RPUSH user 消息到 conv:{session_id}
  ├─ HINCRBY state:{session_id} turn_count 1，读出新 turn_id
  │
  ├─ [step 循环，最多 10 步]
  │   │
  │   ├─ LRANGE conv:{session_id} 0 -1  →  读完整 conversation
  │   ├─ POST /plan { conversation }
  │   │   ├─ has_tool_calls=false → 取 response.message.content 作为最终回复，break
  │   │   └─ has_tool_calls=true  → 取 response.actions[]
  │   │
  │   ├─ RPUSH assistant 消息（含 tool_calls）到 conv:{session_id}
  │   ├─ POST /execute { session_id, actions }
  │   ├─ RPUSH 各 tool result 消息到 conv:{session_id}
  │   └─ 继续下一步
  │
  ├─ RPUSH 最终 assistant 消息到 conv:{session_id}
  ├─ 将 turn_log 序列化后追加到 state:{session_id} turn_logs
  │
  └─ 返回 { reply, turn_id } 给 Gateway
```

**system_prompt 注入规则：**
Orchestrator 在 startup 时从 config.yaml 加载 system_prompt（只读 config，不持有其他运行时对象）。
仅当 `conv:{session_id}` 为空时写入，后续 turn 不重复注入。

---

## 七、部署拓扑

### 容器化方案

| 项目 | 决策 |
|------|------|
| 编排工具 | Docker Compose（单机多容器） |
| Dockerfile | 每个服务各自独立一个 |
| Redis / PostgreSQL | 外部独立部署，不入 Compose |
| 服务间网络 | Docker 内部网络，仅 Gateway:8000 对外暴露 |
| 配置注入 | `.env` 文件 + docker-compose `env_file` 引用 |

### 新增文件目录结构

```
rag_system/
├── gateway/
│   └── Dockerfile
├── orchestrator/
│   └── Dockerfile
├── planner/
│   └── Dockerfile
├── executor/
│   └── Dockerfile
├── rag/
│   └── Dockerfile
├── docker-compose.yml
└── .env.example          # 记录所需环境变量，不提交真实值
```

### docker-compose.yml 结构

```yaml
version: "3.9"

networks:
  agent-net:              # 内部网络，服务间通过容器名互访
    driver: bridge

services:
  gateway:
    build: ./gateway
    ports:
      - "8000:8000"       # 唯一对外暴露的端口
    networks: [agent-net]
    env_file: .env
    depends_on: [orchestrator]

  orchestrator:
    build: ./orchestrator
    networks: [agent-net]
    env_file: .env
    depends_on: [planner, executor]

  planner:
    build: ./planner
    networks: [agent-net]
    env_file: .env

  executor:
    build: ./executor
    networks: [agent-net]
    env_file: .env
    depends_on: [rag]

  rag:
    build: ./rag
    networks: [agent-net]
    env_file: .env
    volumes:
      - ./equipment_knowledge.txt:/app/equipment_knowledge.txt:ro
      - chroma_data:/app/chroma_db

volumes:
  chroma_data:            # ChromaDB 持久化，避免每次重启重新索引
```

> Redis 和 PostgreSQL 在 Compose 外部独立运行，地址通过 `.env` 注入。

### .env.example

```
# LLM
DEEPSEEK_API_KEY=your_key_here

# Redis（外部）
REDIS_URL=redis://host.docker.internal:6379

# PostgreSQL（外部）
POSTGRES_URL=postgresql://user:password@host.docker.internal:5432/fault_history

# 内部服务地址（docker 内网，按容器名）
ORCHESTRATOR_URL=http://orchestrator:8001
PLANNER_URL=http://planner:8002
EXECUTOR_URL=http://executor:8003
RAG_URL=http://rag:8004
```

### 端口分配

| 服务 | 容器内端口 | 宿主机映射 |
|------|-----------|-----------|
| Gateway | 8000 | 8000（对外） |
| Orchestrator | 8001 | 不映射 |
| Planner | 8002 | 不映射 |
| Executor | 8003 | 不映射 |
| RAG Service | 8004 | 不映射 |

---

## 八、错误传播设计

### 错误分层原则

两层独立，语义清晰：

| 层次 | 表达方式 | 含义 |
|------|---------|------|
| 协议层 | HTTP 状态码 | 网络 / 服务可用性问题，调用方按状态码决定是否重试 |
| 业务层 | body `{ok, code, message}` | 业务逻辑失败，调用方按业务码处理 |

**HTTP 状态码语义（全服务统一）：**

| 状态码 | 含义 |
|--------|------|
| 200 | 调用成功，业务结果看 body 的 `ok` 字段 |
| 400 | 调用方传参错误 |
| 409 | 并发冲突（同 session 锁被占用，Gateway 层） |
| 500 | 被调用服务内部不可预期异常 |
| 503 | 被调用服务的依赖不可用（LLM API / Redis / PostgreSQL 挂了） |
| 504 | 网关超时（调用下游超时） |

### 各跳错误处理策略

#### Orchestrator → Planner

| 场景 | 处理 |
|------|------|
| Planner 返回 5xx 或超时 | 指数退避重试 3 次（1s → 2s → 4s） |
| 重试后仍失败 | 终止本轮，向 Gateway 返回 500 + 错误信息 |
| Planner 返回 200 但响应解析失败 | 不重试，直接终止，返回业务错误码 |

#### Orchestrator → Executor

| 场景 | 处理 |
|------|------|
| Executor 返回 5xx 或超时 | 终止本轮，向 Gateway 返回 500 |
| Executor 返回 200 + 部分工具 ok=false | 正常处理：含失败信息的 tool_events 全部写入 conversation，让 LLM 自行应对 |

> **工具失败隔离原则：** 单个工具失败不阻塞其他工具，所有结果（含失败）一并返回给 Orchestrator。

#### Executor → RAG Service（search_knowledge 内部）

| 场景 | 处理 |
|------|------|
| RAG Service 返回 5xx 或超时 | 指数退避重试 3 次（1s → 2s → 4s） |
| 重试后仍失败 | 返回 `{ok: false, code: "E_RAG_UNAVAILABLE"}` 的 ToolResult |

#### Gateway → Orchestrator

| 场景 | 处理 |
|------|------|
| Orchestrator 返回 5xx 或超时 | 不重试，直接向 Client 返回 500 |
| 锁等待超时（3 次重试后） | 返回 409 Conflict |

### 重试策略汇总

| 调用跳 | 是否重试 | 策略 |
|--------|---------|------|
| Orchestrator → Planner | 是 | 指数退避 3 次（1s/2s/4s） |
| Executor → RAG Service | 是 | 指数退避 3 次（1s/2s/4s） |
| Gateway → Orchestrator | 否 | 直接返回 500 |
| Orchestrator → Executor | 否 | 直接终止本轮 |

### 错误最终呈现（Gateway 统一转换）

```
// 成功
{ "reply": "...", "session_id": "...", "turn_id": 1 }

// 失败（无论哪层出错，Gateway 统一格式）
{ "error": "服务暂时不可用，请稍后重试", "code": "E_LLM_UNAVAILABLE" }
```

用户不感知内部服务拓扑，只看到统一的 `error + code` 结构。

---

## 九、实施顺序

### 总体策略

**按服务一次切一个**。每步完成后整个系统仍可正常运行，用 curl 验证通过再进行下一步，出问题可随时回滚。

### 完整步骤

| 步骤 | 内容 | 验证点 |
|------|------|--------|
| Step 1 | **Gateway + Redis**：SessionStore 内部实现换成 Redis，其余模块仍是函数调用 | 正常对话 + 多轮记忆 + 重启后 session 不丢失 |
| Step 2 | **Planner 独立**：拆成 FastAPI 服务（:8002），Orchestrator 改 HTTP 调用 | LLM 推理正常返回 |
| Step 3 | **RAG Service 独立**：拆成 FastAPI 服务（:8004），search_knowledge 内部改 HTTP 调用 | 知识库问题能正确召回 |
| Step 4 | **Executor 独立**：拆成 FastAPI 服务（:8003），Orchestrator 改 HTTP 调用 | 三种工具（search / calc / sql）均正常 |
| Step 5 | **Orchestrator 独立**：拆成 FastAPI 服务（:8001），Gateway 改 HTTP 调用 | 完整 ReAct 多步推理链路正常 |
| Step 6 | **Docker Compose 编排**：各服务 Dockerfile + docker-compose.yml + .env.example | docker compose up 后全链路通 |

### 每步验证的三个 curl 场景

```bash
# 场景 1：直接回答（无工具调用）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你是谁？", "session_id": "test-1"}'

# 场景 2：工具调用（触发 search_knowledge）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "808D轴承异响如何排查？", "session_id": "test-2"}'

# 场景 3：多轮记忆（第二条引用第一条）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "我刚才问的是什么？", "session_id": "test-2"}'
```

三个场景全部返回正确结果，该步骤验证通过，再进行下一步。

---

## 十、原单进程状态对照表（改造参考）

| 原位置 | 原状态 | 分布式去向 |
|--------|--------|-----------|
| `app.state.runtime["client"]` | OpenAI/DeepSeek 客户端 | → Planner 进程内持有 |
| `app.state.runtime["config"]` | 配置字典 | → 各服务各自从 config.yaml 读取 |
| `app.state.runtime["collection"]` | ChromaDB collection | → RAG Service 进程内持有 |
| `app.state.runtime["embedding_model"]` | SentenceTransformer 模型 | → RAG Service 进程内持有 |
| `app.state.runtime["tool_registry"]` | 工具函数字典 | → Executor 进程内持有 |
| `SessionStore["conversation"]` | 消息历史 list | → Redis `conv:{session_id}` |
| `SessionStore["session_state"]` | 元数据 dict | → Redis `state:{session_id}` |
| `SessionStore["lock"]` | threading.Lock | → Redis `lock:{session_id}`（分布式锁） |
| `turn_context`（临时 dict） | runtime + conversation 合并 | → 拆解：各服务自有 config，conversation 从 Redis 读 |
| `fault_history.db`（SQLite） | 故障历史数据 | → PostgreSQL 独立服务 |
