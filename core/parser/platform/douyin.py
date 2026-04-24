from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from ...types import ParseResult
from ..base import BaseMediaParser


class DouyinParser(BaseMediaParser):
    def __init__(self):
        super().__init__("douyin")
        self.semaphore = asyncio.Semaphore(6)
        self.user_agent = (
            "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/116.0.0.0 Mobile Safari/537.36"
        )
        self.headers = {
            "User-Agent": self.user_agent,
            "Referer": "https://www.douyin.com/",
            "Accept-Encoding": "gzip, deflate",
        }

    def can_parse(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        if "douyin.com" not in u:
            return False
        if self._is_live_url(url):
            return False
        return True

    def extract_links(self, text: str) -> List[str]:
        if not text:
            return []

        seen: set[str] = set()
        out: List[str] = []

        patterns = [
            r"https?://v\.douyin\.com/[^\s<>\"'()]+",
            r"https?://(?:www\.)?douyin\.com/(?:video|note)/\d+[^\s<>\"'()]*",
            r"https?://(?:www\.)?douyin\.com/[^\s<>\"'()]*\d{19}[^\s<>\"'()]*",
        ]

        for pattern in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                link = m.group(0)
                if not link or link in seen:
                    continue
                if self._is_live_url(link):
                    continue
                seen.add(link)
                out.append(link)

        return out

    async def parse(self, session: aiohttp.ClientSession, url: str) -> Optional[ParseResult]:
        async with self.semaphore:
            redirected_url = await self._resolve_url(session, url)
            if self._is_live_url(url) or self._is_live_url(redirected_url):
                return None

            is_note = "/note/" in redirected_url or "/note/" in url
            item_id = self._extract_item_id(redirected_url, is_note=is_note) or self._extract_item_id(url, is_note=is_note)
            if not item_id:
                raise RuntimeError("invalid douyin url")

            info = await self._fetch_item_info(session, item_id, is_note=is_note)
            if not info:
                raise RuntimeError("failed to fetch douyin item")

            title = info.get("title", "")
            author = info.get("author", "")
            timestamp = info.get("timestamp", "")
            images = info.get("image_urls", [])
            video_url = info.get("video_url", "")

            if images:
                return ParseResult(
                    url=redirected_url,
                    title=title,
                    author=author,
                    desc="",
                    timestamp=timestamp,
                    platform=self.name,
                    image_urls=images,
                    video_urls=[],
                    image_headers={"User-Agent": self.user_agent, "Referer": "https://www.douyin.com/"},
                    video_headers={"User-Agent": self.user_agent},
                )

            if video_url:
                return ParseResult(
                    url=redirected_url,
                    title=title,
                    author=author,
                    desc="",
                    timestamp=timestamp,
                    platform=self.name,
                    image_urls=[],
                    video_urls=[[video_url]],
                    image_headers={"User-Agent": self.user_agent, "Referer": "https://www.douyin.com/"},
                    video_headers={"User-Agent": self.user_agent},
                    force_pre_download=True,
                )

            raise RuntimeError("douyin item has no media")

    async def _resolve_url(self, session: aiohttp.ClientSession, url: str) -> str:
        try:
            async with session.head(url, allow_redirects=True, headers=self.headers) as resp:
                return str(resp.url)
        except Exception:
            async with session.get(url, allow_redirects=True, headers=self.headers) as resp:
                return str(resp.url)

    def _extract_item_id(self, url: str, is_note: bool) -> str:
        if is_note:
            m = re.search(r"/note/(\d+)", url)
            return m.group(1) if m else ""

        m = re.search(r"/video/(\d+)", url)
        if m:
            return m.group(1)

        m = re.search(r"(\d{19})", url)
        return m.group(1) if m else ""

    async def _fetch_item_info(self, session: aiohttp.ClientSession, item_id: str, is_note: bool) -> Optional[Dict[str, Any]]:
        page_url = (
            f"https://www.iesdouyin.com/share/note/{item_id}/"
            if is_note
            else f"https://www.iesdouyin.com/share/video/{item_id}/"
        )
        async with session.get(page_url, headers=self.headers) as resp:
            resp.raise_for_status()
            html = await resp.text()

        router_data = self._extract_router_data(html)
        if not router_data:
            return None

        try:
            payload = json.loads(router_data.replace("\\u002F", "/").replace("\\/", "/"))
        except Exception:
            return None

        loader_data = payload.get("loaderData", {}) or {}
        target = None
        for value in loader_data.values():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("videoInfoRes"), dict):
                target = value.get("videoInfoRes")
                break
            if isinstance(value.get("noteDetailRes"), dict):
                target = value.get("noteDetailRes")
                break

        if not isinstance(target, dict):
            return None

        item_list = target.get("item_list") or []
        if not item_list or not isinstance(item_list[0], dict):
            return None

        item = item_list[0]
        title = str(item.get("desc", "") or "")
        author_info = item.get("author") or {}
        nickname = str(author_info.get("nickname", "") or "")
        unique_id = str(author_info.get("unique_id", "") or "")
        author = f"{nickname}(uid:{unique_id})" if nickname and unique_id else (nickname or unique_id)

        timestamp = ""
        create_time = item.get("create_time")
        if isinstance(create_time, int) and create_time > 0:
            timestamp = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d")

        image_urls: List[List[str]] = []
        for img in (item.get("images") or []):
            if not isinstance(img, dict):
                continue
            url_list = img.get("url_list") or []
            valid = [u for u in url_list if isinstance(u, str) and u.startswith(("http://", "https://"))]
            if valid:
                image_urls.append(valid)

        video_url = ""
        if not image_urls:
            play_addr = ((item.get("video") or {}).get("play_addr") or {})
            uri = play_addr.get("uri")
            if isinstance(uri, str) and uri:
                if uri.startswith("https://"):
                    video_url = uri
                else:
                    video_url = f"https://www.douyin.com/aweme/v1/play/?video_id={uri}"

        return {
            "title": title,
            "author": author,
            "timestamp": timestamp,
            "image_urls": image_urls,
            "video_url": video_url,
        }

    def _extract_router_data(self, html: str) -> str:
        marker = "window._ROUTER_DATA = "
        start = html.find(marker)
        if start == -1:
            return ""

        brace_start = html.find("{", start)
        if brace_start == -1:
            return ""

        depth = 0
        for i in range(brace_start, len(html)):
            ch = html[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return html[brace_start : i + 1]

        return ""

    def _is_live_url(self, url: str) -> bool:
        if not url:
            return False
        low = url.lower()
        if "live.douyin.com" in low:
            return True
        try:
            parsed = urlparse(low)
            path = parsed.path or ""
            if path.startswith("/live") or "/live/" in path:
                return True
        except Exception:
            return False
        return False
