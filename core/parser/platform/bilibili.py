from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from ...types import ParseResult
from ..base import BaseMediaParser


class BilibiliParser(BaseMediaParser):
    def __init__(
        self,
        max_video_minutes: int = 0,
        over_limit_message: str = "视频较长，请前往B站观看：{url}",
    ):
        super().__init__("bilibili")
        self.semaphore = asyncio.Semaphore(6)
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self.headers = {
            "User-Agent": self.user_agent,
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept-Encoding": "gzip, deflate",
        }
        self.max_video_minutes = max(0, int(max_video_minutes or 0))
        self.over_limit_message = str(over_limit_message or "视频较长，请前往B站观看：{url}")

    def can_parse(self, url: str) -> bool:
        if not url:
            return False
        low = url.lower()
        if self._is_live_url(low):
            return False
        if "b23.tv" in low:
            return True
        if "bilibili.com" not in low:
            return False
        return any(
            key in low
            for key in (
                "/video/",
                "/opus/",
                "t.bilibili.com/",
            )
        ) or bool(re.search(r"[Bb][Vv][0-9A-Za-z]{10,}", url))

    def extract_links(self, text: str) -> List[str]:
        if not text:
            return []

        links: List[str] = []
        seen = set()

        patterns = [
            r"https?://[Bb]23\.tv/[^\s<>\"'()]+",
            r"https?://(?:www|m|mobile)\.bilibili\.com/video/[^\s<>\"'()]+",
            r"https?://(?:www|m|mobile)\.bilibili\.com/opus/\d+[^\s<>\"'()]*",
            r"https?://t\.bilibili\.com/\d+[^\s<>\"'()]*",
        ]

        for pattern in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                link = m.group(0)
                if not link or link in seen:
                    continue
                if self._is_live_url(link):
                    continue
                seen.add(link)
                links.append(link)

        return links

    async def parse(self, session: aiohttp.ClientSession, url: str) -> Optional[ParseResult]:
        async with self.semaphore:
            final_url = await self._expand_b23(session, url)
            if self._is_live_url(url) or self._is_live_url(final_url):
                return None

            low = final_url.lower()
            if "/opus/" in low or "t.bilibili.com/" in low:
                return await self._parse_opus(session, original_url=url, page_url=final_url)
            return await self._parse_video(session, original_url=url, page_url=final_url)

    async def _expand_b23(self, session: aiohttp.ClientSession, url: str) -> str:
        host = (urlparse(url).netloc or "").lower()
        if host != "b23.tv":
            return url
        try:
            async with session.get(
                url,
                allow_redirects=True,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return str(resp.url)
        except Exception:
            return url

    def _format_over_limit_message(self, display_url: str, title: str, duration_seconds: int) -> str:
        template = self.over_limit_message or "视频较长，请前往B站观看：{url}"
        try:
            return template.format(
                url=display_url,
                title=title,
                duration_seconds=duration_seconds,
                limit_minutes=self.max_video_minutes,
            )
        except Exception:
            return f"视频时长超过 {self.max_video_minutes} 分钟，请前往B站观看：{display_url}"

    async def _parse_video(self, session: aiohttp.ClientSession, original_url: str, page_url: str) -> ParseResult:
        bvid = self._extract_bvid(page_url)
        aid = self._extract_aid(page_url)
        if not bvid and not aid:
            raise RuntimeError("invalid bilibili video url")

        view_data = await self._fetch_view(session, bvid=bvid, aid=aid)
        pages = view_data.get("pages") or []
        cid = None
        p_index = self._extract_p(page_url)
        if isinstance(pages, list) and pages:
            index = min(max(p_index, 1), len(pages)) - 1
            page = pages[index] if isinstance(pages[index], dict) else {}
            cid = page.get("cid")
        if cid is None:
            cid = view_data.get("cid")
        if cid is None:
            raise RuntimeError("cannot resolve bilibili cid")

        play_data = await self._fetch_playurl(session, bvid=bvid, aid=aid, cid=int(cid), referer=page_url)
        video_url = self._extract_play_url(play_data)
        if not video_url:
            raise RuntimeError("cannot resolve bilibili video stream")

        owner = view_data.get("owner") or {}
        pubdate = view_data.get("pubdate")
        timestamp = ""
        if isinstance(pubdate, int) and pubdate > 0:
            timestamp = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")

        title = str(view_data.get("title") or "")
        desc = str(view_data.get("desc") or "")
        author = str(owner.get("name") or "")
        duration_seconds = int(view_data.get("duration") or 0)

        display_url = original_url if "b23.tv" in (urlparse(original_url).netloc or "").lower() else page_url

        if self.max_video_minutes > 0 and duration_seconds > self.max_video_minutes * 60:
            message = self._format_over_limit_message(
                display_url=display_url,
                title=title,
                duration_seconds=duration_seconds,
            )
            return ParseResult(
                url=display_url,
                title=title,
                author=author,
                desc=desc,
                timestamp=timestamp,
                platform=self.name,
                image_urls=[],
                video_urls=[],
                image_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
                video_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
                duration_seconds=duration_seconds,
                media_blocked_message=message,
            )

        return ParseResult(
            url=display_url,
            title=title,
            author=author,
            desc=desc,
            timestamp=timestamp,
            platform=self.name,
            image_urls=[],
            video_urls=[[video_url]],
            image_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
            video_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
            force_pre_download=True,
            duration_seconds=duration_seconds,
        )

    async def _parse_opus(self, session: aiohttp.ClientSession, original_url: str, page_url: str) -> Optional[ParseResult]:
        dynamic_id = self._extract_dynamic_id(page_url)
        if not dynamic_id:
            raise RuntimeError("invalid bilibili opus url")

        payload = await self._fetch_opus_detail(session, dynamic_id=dynamic_id, referer=page_url)
        card = payload.get("card") or {}
        desc_obj = card.get("desc") or {}

        card_raw = card.get("card")
        card_data = {}
        if isinstance(card_raw, str) and card_raw.strip():
            try:
                card_data = json.loads(card_raw)
            except Exception:
                card_data = {}

        item = card_data.get("item") or {}
        title = str(item.get("description") or item.get("content") or "")

        user_profile = desc_obj.get("user_profile") or {}
        info = user_profile.get("info") or {}
        author = str(info.get("uname") or "")

        ts = desc_obj.get("timestamp")
        timestamp = ""
        if isinstance(ts, int) and ts > 0:
            timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        image_urls: List[List[str]] = []
        for pic in item.get("pictures") or []:
            if not isinstance(pic, dict):
                continue
            img = pic.get("img_src")
            if isinstance(img, str) and img.startswith(("http://", "https://")):
                image_urls.append([img])

        if image_urls:
            return ParseResult(
                url=page_url,
                title=title,
                author=author,
                desc="",
                timestamp=timestamp,
                platform=self.name,
                image_urls=image_urls,
                video_urls=[],
                image_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
                video_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
            )

        bvid = self._extract_bvid(page_url)
        aid = self._extract_aid(page_url)
        if not bvid and not aid:
            dump = json.dumps(card_data, ensure_ascii=False)
            bvid = self._extract_bvid(dump)
            aid = self._extract_aid(dump)

        if bvid or aid:
            view_data = await self._fetch_view(session, bvid=bvid, aid=aid)
            cid = view_data.get("cid")
            pages = view_data.get("pages") or []
            if cid is None and isinstance(pages, list) and pages and isinstance(pages[0], dict):
                cid = pages[0].get("cid")
            if cid is not None:
                play_data = await self._fetch_playurl(session, bvid=bvid, aid=aid, cid=int(cid), referer=page_url)
                video_url = self._extract_play_url(play_data)
                if video_url:
                    return ParseResult(
                        url=page_url,
                        title=title or str(view_data.get("title") or ""),
                        author=author or str((view_data.get("owner") or {}).get("name") or ""),
                        desc="",
                        timestamp=timestamp,
                        platform=self.name,
                        image_urls=[],
                        video_urls=[[video_url]],
                        image_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
                        video_headers={"User-Agent": self.user_agent, "Referer": page_url, "Origin": "https://www.bilibili.com"},
                        force_pre_download=True,
                    )

        raise RuntimeError("bilibili opus has no media")

    async def _fetch_view(self, session: aiohttp.ClientSession, bvid: Optional[str], aid: Optional[str]) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if bvid:
            params["bvid"] = bvid
        elif aid:
            params["aid"] = aid

        data = await self._get_json(session, "https://api.bilibili.com/x/web-interface/view", params=params, referer="https://www.bilibili.com")
        return data.get("data") or {}

    async def _fetch_playurl(self, session: aiohttp.ClientSession, bvid: Optional[str], aid: Optional[str], cid: int, referer: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "cid": cid,
            "qn": 80,
            "fnval": 0,
            "fnver": 0,
            "fourk": 1,
        }
        if bvid:
            params["bvid"] = bvid
        elif aid:
            params["aid"] = aid

        data = await self._get_json(session, "https://api.bilibili.com/x/player/playurl", params=params, referer=referer)
        return data.get("data") or {}

    async def _fetch_opus_detail(self, session: aiohttp.ClientSession, dynamic_id: str, referer: str) -> Dict[str, Any]:
        data = await self._get_json(
            session,
            "https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/get_dynamic_detail",
            params={"dynamic_id": dynamic_id},
            referer=referer,
        )
        return data.get("data") or {}

    async def _get_json(self, session: aiohttp.ClientSession, api: str, params: Dict[str, Any], referer: str) -> Dict[str, Any]:
        headers = dict(self.headers)
        headers["Referer"] = referer
        async with session.get(
            api,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)
        if payload.get("code") != 0:
            raise RuntimeError(f"bilibili api error: {payload.get('code')} {payload.get('message')}")
        return payload

    def _extract_play_url(self, data: Dict[str, Any]) -> str:
        durl = data.get("durl") or []
        if isinstance(durl, list) and durl and isinstance(durl[0], dict):
            url = durl[0].get("url")
            if isinstance(url, str) and url:
                return url

        dash = data.get("dash") or {}
        videos = dash.get("video") or []
        if isinstance(videos, list) and videos:
            first = videos[0] if isinstance(videos[0], dict) else {}
            base_url = first.get("baseUrl") or first.get("base_url")
            if isinstance(base_url, str) and base_url:
                return base_url
            backups = first.get("backupUrl") or first.get("backup_url") or []
            if isinstance(backups, list):
                for item in backups:
                    if isinstance(item, str) and item:
                        return item
        return ""

    def _extract_bvid(self, text: str) -> str:
        m = re.search(r"[Bb][Vv][0-9A-Za-z]{10,}", text or "")
        if not m:
            return ""
        raw = m.group(0)
        return "BV" + raw[2:]

    def _extract_aid(self, text: str) -> str:
        m = re.search(r"[Aa][Vv](\d+)", text or "")
        if m:
            return m.group(1)
        parsed = urlparse(text or "")
        query = parse_qs(parsed.query)
        aid = (query.get("aid") or [""])[0]
        if isinstance(aid, str) and aid.isdigit():
            return aid
        return ""

    def _extract_dynamic_id(self, url: str) -> str:
        m = re.search(r"t\.bilibili\.com/(\d+)", url or "", re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"/opus/(\d+)", url or "", re.IGNORECASE)
        if m:
            return m.group(1)
        return ""

    def _extract_p(self, url: str) -> int:
        try:
            p = int((parse_qs(urlparse(url).query).get("p") or ["1"])[0])
            return max(1, p)
        except Exception:
            return 1

    def _is_live_url(self, url: str) -> bool:
        low = (url or "").lower()
        if "live.bilibili.com" in low:
            return True
        try:
            parsed = urlparse(low)
            path = parsed.path or ""
            return path.startswith("/live") or "/live/" in path
        except Exception:
            return False
