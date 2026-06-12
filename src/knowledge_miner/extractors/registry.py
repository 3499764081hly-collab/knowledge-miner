"""提取器注册中心"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_miner.extractors.base import BaseExtractor


class ExtractorRegistry:
    """提取器注册中心"""

    def __init__(self) -> None:
        self._extractors: dict[str, type[BaseExtractor]] = {}

    def register(self, name: str, extractor_class: type[BaseExtractor]) -> None:
        """注册提取器"""
        self._extractors[name] = extractor_class

    def get(self, name: str) -> BaseExtractor | None:
        """获取提取器实例"""
        cls = self._extractors.get(name)
        if cls:
            return cls()
        return None

    def get_all(self) -> list[BaseExtractor]:
        """获取所有提取器实例"""
        return [cls() for cls in self._extractors.values()]

    def list_names(self) -> list[str]:
        """列出所有已注册的提取器名称"""
        return list(self._extractors.keys())
