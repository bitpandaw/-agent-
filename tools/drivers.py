"""懒加载驱动：Neo4j 等。"""

from typing import Any, Optional

from neo4j import GraphDatabase

from config.config_loader import config

_neo4j_driver: Optional[Any] = None


def _get_neo4j_driver() -> Any:
    """获取 Neo4j 驱动单例。"""
    global _neo4j_driver
    if _neo4j_driver is None:
        neo4j_cfg: dict[str, Any] = config["neo4j"]
        _neo4j_driver = GraphDatabase.driver(
            neo4j_cfg["uri"],
            auth=(neo4j_cfg["user"], neo4j_cfg["password"]),
        )
    return _neo4j_driver
