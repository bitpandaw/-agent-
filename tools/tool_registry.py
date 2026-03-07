"""兼容层：从 registry 重新导出 TOOL_REGISTRY。"""

from tools.registry import TOOL_REGISTRY

__all__ = ["TOOL_REGISTRY"]
