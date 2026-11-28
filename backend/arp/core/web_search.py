"""Shared web-search interface types used by both live search clients and test stand-ins."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebSearchClient(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError
