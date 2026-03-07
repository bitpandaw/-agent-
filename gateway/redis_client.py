"""Redis 连接客户端，供 SessionStore 等模块使用。"""

import os
from typing import Any, Optional

import redis

from config.config_loader import config

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """获取 Redis 客户端单例。首次调用时创建连接。"""
    global _redis_client
    if _redis_client is None:
        redis_cfg: dict[str, Any] = config.get("redis", {})
        redis_url: str = os.environ.get(
            redis_cfg.get("url_env", "REDIS_URL"),
            redis_cfg.get("default_url", "redis://localhost:6379"),
        )
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def close_redis() -> None:
    """关闭 Redis 连接（用于 shutdown）。"""
    global _redis_client
    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None
