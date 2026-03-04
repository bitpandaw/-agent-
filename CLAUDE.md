# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Industrial equipment fault diagnosis agent system for SINUMERIK 808D CNC machines. Combines RAG (ChromaDB + sentence-transformers) with a DeepSeek LLM in a ReAct-style loop (Plan → Execute → Repeat) exposed via FastAPI.

**Required env var:** `DEEPSEEK_API_KEY`

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize SQLite DB with sample fault records
python init_db.py

# Start API server
uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/health

# Chat request
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "808D轴承异响如何排查?", "session_id": "test-1"}'

# Run RAG evaluation experiments (in experiments/ directory)
python experiments/gen_verification_report.py
python experiments/run_rag_norm_experiment.py
```

There is no test runner or linter configured. No `setup.py`, `pyproject.toml`, or `Makefile`.

## Architecture

### Data Flow (Single Turn)

```
POST /chat
  → gateway.py: retrieve/create session from SessionStore
  → agent.run_turn(): wraps orchestrator
  → orchestrator.run_orchestrator(): ReAct loop (max 10 steps)
      ├─ planner.plan_actions(): calls DeepSeek with conversation history
      │    └─ if no tool_calls → break with assistant's final answer
      ├─ executor.execute_actions(): dispatches to TOOL_REGISTRY
      │    ├─ search_knowledge → rag_pipeline.retrieve_context()
      │    ├─ calculator → eval() on expression
      │    └─ query_fault_history → SQLite query on fault_history.db
      └─ tool results appended to conversation, loop repeats
  → state_logger.log_turn(): records in session state
  → ChatResponse {reply, session_id, turn_id}
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `gateway/gateway.py` | FastAPI app, `/chat` and `/health` endpoints, startup init |
| `gateway/agent.py` | Initializes runtime (LLM client, ChromaDB, embedding model, knowledge base), exposes `run_turn()` |
| `gateway/SessionStore.py` | Thread-safe per-session storage: conversation history + turn logs + lock |
| `orchestrator/orchestrator.py` | ReAct loop coordinator |
| `planner/planner.py` | Calls DeepSeek with OpenAI function-calling format, parses tool_calls, retries up to 10x |
| `executor/executor.py` | Looks up and calls tools from TOOL_REGISTRY, returns structured `ToolResult` |
| `tools/tool_registry.py` | Three tool implementations + `TOOL_REGISTRY` dict |
| `tools/tools_json.py` | Tool schemas in OpenAI function-calling format for the LLM |
| `rag/rag_pipeline.py` | Chunk document, index to ChromaDB, retrieve with min-max normalization |
| `config/config.yaml` | All configuration (embedding model, RAG params, LLM endpoint, file paths) |
| `state/state_logger.py` | Structured turn logging |

### Key Data Contracts

**PlanAction**: `{tool_name, tool_args, tool_call_id}`

**ToolResult**: `{ok, code, message, payload, latency_ms, tool_name}`

**ChatRequest / ChatResponse**:
```json
// Request
{"message": "string", "session_id": "string (optional)"}
// Response
{"reply": "string", "session_id": "string", "turn_id": int}
```

### Configuration

All knobs are in `config/config.yaml`. Key settings:
- `rag.top_k`: number of retrieved chunks (default 4)
- `rag.score_threshold`: min-max normalized score cutoff (default 0.3)
- `rag.distance`: ChromaDB distance metric (`cosine`, `l2`, `ip`)
- `llm.api_key_env`: env var name for the API key (`DEEPSEEK_API_KEY`)
- `paths.knowledge_file`: path to the knowledge base text (`equipment_knowledge.txt`)

### RAG Pipeline Notes

- Knowledge base (`equipment_knowledge.txt`, ~1.1MB) is chunked by blank lines at startup and loaded into an **in-memory** ChromaDB collection — data is lost on server restart.
- Retrieval uses min-max normalization: `norm = (d_max - d) / (d_max - d_min + eps)` to handle single-result edge cases.
- `retrieve_context_raw()` returns unnormalized L2 distances for comparison/experiments.

### Session Management

`SessionStore` holds all sessions in memory (no persistence). Each session contains:
- `conversation`: full message list in OpenAI format (system prompt auto-prepended)
- `session_state`: metadata + `turn_logs`
- `lock`: per-session `threading.Lock`

### Known Issues

- `get_embedding_model()` is imported in `agent.py` and experiments but the export from `tool_registry.py` may be missing — check before modifying tool_registry.
- ChromaDB collection is in-memory only; re-indexing happens on every server start.
- No API authentication or rate limiting.
