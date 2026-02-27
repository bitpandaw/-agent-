# 架构文档

## 1. 范围与目标
- 今日目标：把单文件可运行原型整理为可扩展工程骨架，保证功能不回退。
- 当前系统定位：工业设备故障诊断 Agent（LLM + RAG + SQL 工具）。
- 非目标：不在 Day1 追求性能优化、复杂调度策略、完整监控平台。

## 2. 系统概览
- 主入口：`rag_system.py`
- 工具注册与实现：`tools/tool_registry.py`
- 工具 schema：`tools/tools_json.py`
- 配置加载：`config/config_loader.py`
- 配置文件：`config/config.yaml`
- 数据初始化：`init_db.py`
- 知识库文本：`equipment_knowledge.txt`
- 历史故障库：`fault_history.db`

## 3. 模块契约

| Module        | 职责                                   | 输入                                     | 输出                                              | 依赖                                     | 失败处理                                 | 当前代码映射                                                 |
| ------------- | -------------------------------------- | ---------------------------------------- | ------------------------------------------------- | ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------ |
| entry         | 负责单轮对话编排与循环控制             | 用户输入、历史消息、配置                 | Assistant 回复、工具调用事件                      | OpenAI client、Chroma collection、config | 启动失败直接终止；交互失败进入重试或报错 | `rag_system.py` `main()`                                     |
| planner       | 基于上下文决定是否调用工具与参数       | `TurnInput`（用户消息+历史）             | `PlanAction[]`（tool_name + tool_args）或直接回复 | LLM、`TOOLS_LIST`                        | LLM 调用失败重试，最终返回错误           | `rag_system.py` `client.chat.completions.create(...)`        |
| executor      | 执行 planner 产出的工具动作            | `PlanAction[]`、运行时依赖（collection） | `ToolResult[]`                                    | `TOOL_REGISTRY`、`call_tool`             | 未知工具/参数错误统一返回错误结构        | `rag_system.py` `call_tool()` + tool_calls loop              |
| tools         | 提供业务能力（计算、RAG检索、SQL查询） | 工具参数                                 | 业务结果                                          | sqlite3、sentence-transformers、chromadb | 每个工具内部兜底，返回可读错误           | `tools/tool_registry.py`                                     |
| rag           | 文档分块、索引、向量检索、阈值策略     | query、knowledge chunks、RAG配置         | 检索文档列表或空结果                              | embedding model、collection、config.rag  | 检索失败返回错误；无命中返回空           | `rag_system.py` `load_and_chunk_document/index_documents` + `tool_registry.py::search_knowledge` |
| state/logging | 记录会话与故障排查信息                 | 每轮输入输出、工具执行事件、错误         | 可回放状态与调试日志                              | 内存会话、stdout（当前）                 | 日志失败不阻塞主流程                     | 当前以 `conversation` 内存列表与 `print` 为主                |

## 4. 数据契约

### 4.1 TurnInput
- `session_id`: string
- `turn_id`: integer
- `user_input`: string
- `history`: list

### 4.2 PlanAction
- `tool_name`: string
- `tool_args`: object

### 4.3 ToolResult (目标统一结构)
- `ok`: boolean
- `code`: string
- `message`: string
- `latency_ms`: number
- `payload`: object

### 4.4 TurnState
- `session_id`: string
- `turn_id`: integer
- `user_input`: string
- `assistant_output`: string
- `tool_events`: list
- `error`: object or null
- `timestamp`: string

## 5. 端到端流程
1. entry 读取配置并初始化 LLM client、Chroma collection。
2. entry 加载知识库文本并建立/更新向量索引。
3. entry 接收用户输入，组装 `TurnInput`。
4. planner 调用 LLM 生成回答或 `tool_calls`。
5. executor 解析 `tool_calls`，映射到 `TOOL_REGISTRY` 执行。
6. tools/rag 返回结果并写回对话上下文。
7. planner（LLM）基于工具结果生成最终回复。
8. entry 输出回复并记录 state/logging。

## 6. 失败路径

| 场景                  | 触发点                              | code               | 用户可见信息                              | 重试策略               | state记录                                           |
| --------------------- | ----------------------------------- | ------------------ | ----------------------------------------- | ---------------------- | --------------------------------------------------- |
| 配置文件缺失/格式错误 | `read_config()`                     | `E_CONFIG_LOAD`    | 配置读取失败，请检查 `config/config.yaml` | 不重试，启动终止       | `stage=config`, `error`, `timestamp`                |
| LLM 调用超时/失败     | planner 调用 chat completions       | `E_LLM_TIMEOUT`    | 模型服务暂时不可用，请稍后重试            | 最多重试3次            | `stage=planner`, `retry_count`, `error`             |
| 工具名不存在          | executor 查 `TOOL_REGISTRY`         | `E_TOOL_NOT_FOUND` | 工具不可用：`{tool_name}`                 | 不重试                 | `stage=executor`, `tool_name`, `error`              |
| 工具参数不匹配        | `call_tool()` 触发 `TypeError`      | `E_TOOL_ARG`       | 工具参数错误，请调整请求                  | 不重试                 | `stage=executor`, `tool_name`, `tool_args`, `error` |
| RAG 检索失败          | `collection.query()` 异常           | `E_RAG_QUERY`      | 知识库检索失败                            | 最多重试3次            | `stage=rag`, `query`, `error`                       |
| RAG 无命中            | 检索结果为空                        | `E_RAG_EMPTY`      | 未检索到相关知识                          | 不重试，返回空结果分支 | `stage=rag`, `query`, `top_k`, `threshold`          |
| SQL 查询失败          | `query_fault_history` 执行 SQL 异常 | `E_SQL_QUERY`      | 故障历史查询失败                          | 不重试                 | `stage=tool_sql`, `sql`, `error`                    |

## 7. 工具契约规范
- 目标策略：所有工具统一返回 `ToolResult` 结构。
- 当前状态：工具仍有字符串返回，主循环依赖 `str(result)`。
- Day1 要求：主循环只处理统一结构，不做工具特判。

## 8. 可扩展性说明（面向百工具规模）
- 工具扩展通过注册表完成，避免在主流程堆叠 if-else。
- planner 只产出 `PlanAction`，executor 只消费 `PlanAction`，职责解耦。
- 新增工具的变更面可控制在 `tools_json + tool_registry`，主编排不改。
- 统一 `ToolResult` 让失败语义、日志、回归测试可标准化。
- 模块边界清晰后，可逐步替换任一层实现而不影响全链路。

## 9. 已知差距（当前代码 vs 目标）
- `rag_system.py` 仍包含部分 RAG 细节（分块/索引）与 executor 细节。
- `score_threshold` 已在配置中存在，但尚未实质参与检索过滤。
- state/logging 目前主要是内存 `conversation` 与控制台输出，缺持久化。
- 工具返回结构尚未完全统一为 `ToolResult`。

## 10. 验收清单
- [ ] `Module Contracts` 六模块均有职责、输入、输出、依赖、失败处理、代码映射。
- [ ] `Data Contracts` 已定义 `TurnInput/PlanAction/ToolResult/TurnState`。
- [ ] `Failure Paths` 至少覆盖 5 个高频故障场景并包含 `code + state记录`。
- [ ] 主流程、工具层、RAG层边界可按文档映射到实际文件。
- [ ] 文档中的策略与当前配置项（`top_k/score_threshold/db.path/llm.model`）一致。