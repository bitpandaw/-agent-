# tools_json.py
TOOLS_LIST = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a math expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expression to evaluate, e.g. '25*4'."
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the equipment knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_fault_history",
            "description": "查询设备的历史故障记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {
                        "type": "string",
                        "description": "设备编号,如EQ001(可选)"
                    },
                    "fault_type": {
                        "type": "string",
                        "description": "故障类型，如'轴承异响'（可选）"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_graph",
            "description": "在故障诊断知识图谱中进行多跳推理查询。适合：根据报警号查关联部件和机床数据、追踪报警交叉引用、发现共享同一参数的报警。当用户提到具体报警号或需要关联分析时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "alarm_id": {
                        "type": "string",
                        "description": "报警编号，如'2000'或'10720'（可选）"
                    },
                    "query": {
                        "type": "string",
                        "description": "关键词查询，如'温度'或'PLC'（可选，当没有具体报警号时使用）"
                    }
                }
            }
        }
    },
]
