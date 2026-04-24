from __future__ import annotations

import asyncio
from typing import Dict, Any, List, Optional, Tuple

import aiohttp

from .base import BaseMediaParser
from .router import LinkRouter


class ParserManager:
    def __init__(self, parsers: List[BaseMediaParser]):
        if not parsers:
            raise ValueError("parsers cannot be empty")
        self.parsers = parsers
        self.router = LinkRouter(parsers)

    def extract_all_links(self, text: str) -> List[Tuple[str, BaseMediaParser]]:
        return self.router.extract_links_with_parser(text)

    async def parse_text(
        self,
        text: str,
        session: aiohttp.ClientSession,
        links_with_parser: Optional[List[Tuple[str, BaseMediaParser]]] = None,
    ) -> List[Dict[str, Any]]:
        pairs = links_with_parser or self.extract_all_links(text)
        if not pairs:
            return []

        unique: Dict[str, BaseMediaParser] = {}
        for url, parser in pairs:
            if url not in unique:
                unique[url] = parser

        tasks = [parser.parse(session, url) for url, parser in unique.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: List[Dict[str, Any]] = []
        items = list(unique.items())
        for idx, result in enumerate(results):
            url, parser = items[idx]
            if isinstance(result, Exception):
                out.append({
                    "url": url,
                    "platform": parser.name,
                    "error": str(result),
                    "image_urls": [],
                    "video_urls": [],
                    "image_headers": {},
                    "video_headers": {},
                })
                continue

            if result is None:
                continue
            data = result.as_dict()
            if "platform" not in data or not data["platform"]:
                data["platform"] = parser.name
            out.append(data)

        return out
