from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from ...types import ParseResult
from ..base import BaseMediaParser


TWITTER_BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOu"
    "H5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
GUEST_ACTIVATE_API = "https://api.twitter.com/1.1/guest/activate.json"
GRAPHQL_TWEET_API = (
    "https://api.twitter.com/graphql/"
    "kPLTRmMnzbPTv70___D06w/TweetResultByRestId"
)


class TwitterXParser(BaseMediaParser):
    def __init__(
        self,
        use_parse_proxy: bool = False,
        use_image_proxy: bool = True,
        use_video_proxy: bool = True,
        proxy_url: Optional[str] = None,
        primary_api_base: str = "https://api.fxtwitter.com/status",
    ):
        super().__init__("twitter_x")
        self.use_parse_proxy = use_parse_proxy
        self.use_image_proxy = use_image_proxy
        self.use_video_proxy = use_video_proxy
        self.proxy_url = proxy_url
        self.primary_api_base = primary_api_base.rstrip("/")
        self.semaphore = asyncio.Semaphore(6)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

    def can_parse(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        return (
            ("twitter.com" in u or "x.com" in u)
            and re.search(r"/status/(\d+)", u) is not None
        )

    def extract_links(self, text: str) -> List[str]:
        pattern = re.compile(
            r"https?://(?:twitter\.com|x\.com)/[^\s]*?/status/(\d+)[^\s<>\"'()]*",
            re.IGNORECASE,
        )
        seen_ids = set()
        out: List[str] = []
        for m in pattern.finditer(text or ""):
            tweet_id = m.group(1)
            if tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)
            out.append(m.group(0))
        return out

    async def parse(self, session: aiohttp.ClientSession, url: str) -> Optional[ParseResult]:
        async with self.semaphore:
            m = re.search(r"/status/(\d+)", url)
            if not m:
                raise RuntimeError("invalid twitter/x status url")
            tweet_id = m.group(1)

            media_info = None
            primary_error = None
            try:
                media_info = await self._fetch_primary(session, tweet_id)
            except Exception as e:
                primary_error = e

            if media_info is None:
                media_info = await self._fetch_graphql(session, tweet_id)

            return self._build_result(url, media_info, primary_error)

    def _parse_time(self, created_at: str) -> str:
        if not created_at:
            return ""
        try:
            dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return created_at

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\s*https://t\.co/[^\s,]+$", "", text).strip()

    async def _fetch_primary(self, session: aiohttp.ClientSession, tweet_id: str) -> Dict[str, Any]:
        proxy = self.proxy_url if self.use_parse_proxy else None
        url = f"{self.primary_api_base}/{tweet_id}"
        async with session.get(
            url,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=25),
            proxy=proxy,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        return self._from_primary_payload(data)

    def _from_primary_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tweet = payload.get("tweet") or {}
        if not isinstance(tweet, dict):
            raise RuntimeError("primary api returned invalid tweet payload")

        author_info = tweet.get("author") or {}
        author_name = author_info.get("name", "") if isinstance(author_info, dict) else ""
        author_username = author_info.get("screen_name", "") if isinstance(author_info, dict) else ""
        author = f"{author_name}(@{author_username})" if author_name else author_username

        info = {
            "text": tweet.get("text", "") or "",
            "author": author,
            "timestamp": self._parse_time(tweet.get("created_at", "")),
            "images": [],
            "videos": [],
        }

        media = tweet.get("media") or {}
        photos = media.get("photos") or []
        videos = media.get("videos") or []

        for item in photos:
            if isinstance(item, dict) and item.get("url"):
                info["images"].append(item["url"])

        for item in videos:
            if isinstance(item, dict) and item.get("url"):
                info["videos"].append({"url": item["url"]})

        return info

    async def _fetch_graphql(self, session: aiohttp.ClientSession, tweet_id: str) -> Dict[str, Any]:
        guest_token = await self._get_guest_token(session)
        proxy = self.proxy_url if self.use_parse_proxy else None

        features = {
            "responsive_web_graphql_exclude_directive_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "rweb_video_timestamps_enabled": True,
        }
        params = {
            "variables": json.dumps(
                {
                    "tweetId": tweet_id,
                    "withCommunity": False,
                    "includePromotedContent": False,
                    "withVoice": False,
                },
                separators=(",", ":"),
            ),
            "features": json.dumps(features, separators=(",", ":")),
            "fieldToggles": json.dumps(
                {"withArticleRichContentState": True, "withArticlePlainText": False},
                separators=(",", ":"),
            ),
        }

        headers = {
            "authorization": TWITTER_BEARER_TOKEN,
            "x-guest-token": guest_token,
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
            "user-agent": self.headers["User-Agent"],
            "content-type": "application/json",
        }

        async with session.get(
            GRAPHQL_TWEET_API,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=25),
            proxy=proxy,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        errors = data.get("errors") or []
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            raise RuntimeError(f"graphql error: {message}")

        result = (((data.get("data") or {}).get("tweetResult") or {}).get("result")) or {}
        tweet = result.get("tweet") if isinstance(result.get("tweet"), dict) else result
        legacy = tweet.get("legacy") or {}
        if not legacy:
            raise RuntimeError("graphql returned empty legacy tweet")

        return self._from_graphql(tweet, legacy)

    async def _get_guest_token(self, session: aiohttp.ClientSession) -> str:
        proxy = self.proxy_url if self.use_parse_proxy else None
        headers = {
            "authorization": TWITTER_BEARER_TOKEN,
            "user-agent": self.headers["User-Agent"],
        }
        async with session.post(
            GUEST_ACTIVATE_API,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            proxy=proxy,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        token = str(data.get("guest_token") or "").strip()
        if not token:
            raise RuntimeError("guest token not found")
        return token

    def _best_variant(self, variants: List[Dict[str, Any]]) -> str:
        mp4s = [v for v in variants if isinstance(v, dict) and v.get("content_type") == "video/mp4" and v.get("url")]
        if mp4s:
            mp4s.sort(key=lambda x: int(x.get("bitrate") or x.get("bit_rate") or 0), reverse=True)
            return mp4s[0]["url"]
        for v in variants:
            if isinstance(v, dict) and v.get("url"):
                return v["url"]
        return ""

    def _from_graphql(self, tweet: Dict[str, Any], legacy: Dict[str, Any]) -> Dict[str, Any]:
        note_text = (((tweet.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")
        full_text = note_text or legacy.get("full_text", "")
        text = self._clean_text(full_text)

        user_result = (((tweet.get("core") or {}).get("user_results") or {}).get("result")) or {}
        user_legacy = user_result.get("legacy") or {}
        author_name = user_legacy.get("name", "")
        author_username = user_legacy.get("screen_name", "")
        author = f"{author_name}(@{author_username})" if author_name and author_username else (author_name or author_username)

        info = {
            "text": text,
            "author": author,
            "timestamp": self._parse_time(legacy.get("created_at", "")),
            "images": [],
            "videos": [],
        }

        media = ((legacy.get("extended_entities") or {}).get("media")) or ((legacy.get("entities") or {}).get("media")) or []
        seen = set()
        for item in media:
            if not isinstance(item, dict):
                continue
            mtype = item.get("type")
            if mtype == "photo":
                img = item.get("media_url_https") or ""
                if img:
                    img = f"{img}{'&' if '?' in img else '?'}name=orig"
                if img and img not in seen:
                    seen.add(img)
                    info["images"].append(img)
            elif mtype in ("video", "animated_gif"):
                variants = (item.get("video_info") or {}).get("variants") or []
                best = self._best_variant(variants)
                if best and best not in seen:
                    seen.add(best)
                    info["videos"].append({"url": best})

        return info

    def _build_result(self, url: str, info: Dict[str, Any], primary_error: Optional[Exception]) -> ParseResult:
        images = [x for x in info.get("images", []) if isinstance(x, str) and x]
        videos = [x.get("url") for x in info.get("videos", []) if isinstance(x, dict) and x.get("url")]

        if not images and not videos:
            raise RuntimeError("tweet has no media")

        text = info.get("text", "") or ""
        title = text[:80] if text else "Twitter/X post"

        desc = text
        if primary_error:
            desc = f"{text}\n\n(Primary parse path failed, fallback used.)" if text else "(Primary parse path failed, fallback used.)"

        return ParseResult(
            url=url,
            title=title,
            author=info.get("author", "") or "",
            desc=desc,
            timestamp=info.get("timestamp", "") or "",
            platform=self.name,
            image_urls=[[u] for u in images],
            video_urls=[[u] for u in videos],
            image_headers={"User-Agent": self.headers["User-Agent"]},
            video_headers={"User-Agent": self.headers["User-Agent"]},
            force_pre_download=bool(videos),
            use_image_proxy=self.use_image_proxy,
            use_video_proxy=self.use_video_proxy,
            proxy_url=self.proxy_url if (self.use_image_proxy or self.use_video_proxy or self.use_parse_proxy) else None,
        )
