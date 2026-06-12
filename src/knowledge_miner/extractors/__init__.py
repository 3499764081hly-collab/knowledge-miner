"""数据提取器模块"""

from knowledge_miner.extractors.base import BaseExtractor
from knowledge_miner.extractors.registry import ExtractorRegistry

__all__ = ["BaseExtractor", "ExtractorRegistry"]

# 全局注册中心
registry = ExtractorRegistry()


def register_extractor(name: str):
    """注册提取器装饰器"""
    def decorator(cls):
        registry.register(name, cls)
        return cls
    return decorator


# 自动导入并注册所有提取器
from knowledge_miner.extractors import claude, hermes  # noqa: E402, F401
