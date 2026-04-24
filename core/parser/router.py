from __future__ import annotations

import re
from typing import List, Tuple

from .base import BaseMediaParser


class LinkRouter:
    URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

    def __init__(self, parsers: List[BaseMediaParser]):
        self.parsers = parsers

    def extract_links_with_parser(self, text: str) -> List[Tuple[str, BaseMediaParser]]:
        candidates = []
        for parser in self.parsers:
            links = parser.extract_links(text)
            for link in links:
                pos = text.find(link)
                candidates.append((pos if pos >= 0 else 10**9, link, parser))

        candidates.sort(key=lambda x: x[0])
        seen = set()
        result = []
        for _, link, parser in candidates:
            if link in seen:
                continue
            seen.add(link)
            result.append((link, parser))
        return result

    def find_parser(self, url: str) -> BaseMediaParser | None:
        for parser in self.parsers:
            if parser.can_parse(url):
                return parser
        return None
