# 工业设备故障诊断 Agent 系统

RAG + LLM + 多工具的故障诊断对话系统，基于 SINUMERIK 808D 诊断手册。

## 快速开始

```bash
pip install -r requirements.txt
# 编辑 config/config.yaml 配置 embedding、llm、rag、db
python init_db.py
uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000
```

访问 `POST /chat` 进行对话，`GET /health` 健康检查。

## 主要文件

| 路径 | 说明 |
|------|------|
| `gateway/gateway.py` | FastAPI 入口，`/chat`、`/health` |
| `gateway/agent.py` | 核心逻辑：run_turn、load_knowledge_base |
| `tools/` | 工具注册与定义 |
| `rag/` | RAG 检索与索引 |
| `config/config.yaml` | 统一配置 |
| `equipment_knowledge.txt` | 知识库（808D 诊断手册，可由 `scripts/extract_808d_manual.py` 从 PDF 生成） |

## 项目背景

为准备研究生复试，独立完成。技术选型：DeepSeek + MiniLM + ChromaDB + SQLite，轻量易部署。

## 开发过程

### **单文件跑通**

一开始就是个大文件，RAG、工具调用、LLM 对话都堆在一起，工具用 if-else 分支，加到第三个就不想写了。先把能跑的版本写出来，再考虑拆分。

### **工具解耦与模块拆分**

工具抽到 tool_registry，遇到 ChromaDB collection 传参问题，试过 lambda 注入，最后在入口做了通用接口。同时抽了 config，因为换 DeepSeek 和 MiniLM 后要统一读配置。接着按数据流拆成 entry / planner / executor / rag，并处理了 embedding 分数尺度不一致，做了归一化，顺带加了 state 模块。

### **架构修整与 ReAct**

把 entry 里 planner 的活拆出去，和设计文档对齐，修了解耦带来的 bug。之后上了 ReAct 风格推理，知识库换成 808D 诊断手册，做了归一化对比实验。

### **REST 入口**

加了 Gateway，FastAPI 暴露 /chat，SessionStore 做会话级 context，支持多会话，核心逻辑迁到 agent 模块。

### **待优化**

- RAG 分块策略仍较粗糙
- 数据来源是手册，非真实工业数据

### 技术选型理由

- DeepSeek：选用轻量级本地模型以支持离线部署，降低端侧推理依赖。
- ChromaDB：轻量级本地向量库，适合原型开发
- SQLite：单文件数据库，易于部署演示
