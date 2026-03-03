# 工业设备故障诊断Agent系统

## 快速开始

1. 安装依赖
2. 在config.yaml中配置环境：
  - embedding model
  - llm
  - rag
  - db
3. 初始化数据库：
  - `python init_db.py`
4. 启动程序：
  - `python rag_system.py`

## 主要文件

- `rag_system.py`：主程序入口
- `tools/`：工具定义与注册
- `config/config.yaml`：配置文件
- `equipment_knowledge.txt`：知识库文本（来源：SINUMERIK 808D ADVANCED 诊断手册，可通过 `scripts/extract_808d_manual.py` 从 PDF 重新生成）
- `fault_history.db`：故障历史数据库

## 项目背景

为准备研究生复试，独立自主完成此次项目

## 开发过程

### 已解决的主要问题

1. **工具可扩展性**：一开始在rag_system.py中使用if-else判断分支使用工具，加到第三个工具觉得太麻烦。和claude讨论后决定新开一个tool moudle，用于存储工具注册表。后面遇到了传参的问题（ChromaDB的collection无法解耦合)，发现这个问题后我决定tool_registry中使用*lambda*函数以对函数进行参数注入，后面发现还是太麻烦，于是决定用在rag_system.py设置一个通用接口
2. **可移植性问题**：开发过程中由于openaikey太贵，导致我不得不使用deepseekapi，由于deepseek没有embedding模型，我使用了轻量级开源模型MiniLM，开发过程中考虑到用户可能使用的不是deepseek，而是claude，chatgpt，这时配置可能导致太麻烦，于是我单开了一个config模块用于统一配置，减少硬编码。在开发过程中遇到了不同模块下的路径不同可能导致重新下载MiniLM的问题，于是我统一在tool_registry.py设置了一个get_embedding_model函数，并在里面设置了global embedding_model，通过在单一模块得到模块的位置来避免这个问题
3. **向量检索质量**：发现用户提问越具体，检索效果越好。
4. **模块重构**:由于初始的rag_sytem将多个功能融合到一个模块里，导致后续项目无法正常拓展，通过交流编排数据流后，将原本一个模块划分为多个功能上独立，数据流单元清晰的模块。后续也发现了entry模块执行了大部分的planner模块，重构后得以解决
5. **设计文档和实际模块功能未对齐Z**:实际开发中我并没有完全按照设计文档对齐，后续修复了这个点（除了history和context

### 正在解决的问题

1. **RAG 分块过于粗糙**:rag的文件检索质量严重受到文档的约束，并没有考虑到真实工业场景下的数据
2. **数据来源不是真实的工业数据**:真实的工业数据需要用到数据清洗技术，目前并没有找到真实的数据来源

### 技术选型理由

- DeepSeek：选用轻量级本地模型以支持离线部署，降低端侧推理依赖。
- ChromaDB：轻量级本地向量库，适合原型开发
- SQLite：单文件数据库，易于部署演示

