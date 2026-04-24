from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import aiohttp

from ..types import ParseResult


class BaseMediaParser(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def can_parse(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract_links(self, text: str) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    async def parse(self, session: aiohttp.ClientSession, url: str) -> Optional[ParseResult]:
        raise NotImplementedError
