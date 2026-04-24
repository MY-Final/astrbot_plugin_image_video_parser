from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
import os
import tempfile


@dataclass
class TriggerConfig:
    auto_parse: bool = True
    keywords: List[str] = field(default_factory=lambda: ["解析", "解析视频", "解析推文"])

    def should_parse(self, text: str) -> bool:
        if self.auto_parse:
            return True
        return any(kw and kw in text for kw in self.keywords)


@dataclass
class MessageConfig:
    text_metadata: bool = True
    rich_media: bool = True

    def has_any_output(self) -> bool:
        return self.text_metadata or self.rich_media


@dataclass
class DownloadConfig:
    pre_download_all_media: bool = True
    cache_dir: str = ""


@dataclass
class ProxyConfig:
    address: str = ""
    twitter_use_parse_proxy: bool = False
    twitter_use_image_proxy: bool = True
    twitter_use_video_proxy: bool = True


@dataclass
class ProviderConfig:
    enable_twitter: bool = True
    enable_douyin: bool = True
    enable_bilibili: bool = True


@dataclass
class ReactionConfig:
    enabled: bool = True
    detect_emoji_id: str = "265"
    success_emoji: str = "👌"
    failed_emoji: str = "😭"
    emoji_type: str = "1"


@dataclass
class BilibiliConfig:
    max_video_minutes: int = 0
    over_limit_message: str = "视频较长，请前往B站观看：{url}"


@dataclass
class DebugConfig:
    enabled: bool = False


class ConfigManager:
    def __init__(self, raw: dict):
        self._raw = raw or {}
        self.trigger = TriggerConfig()
        self.message = MessageConfig()
        self.download = DownloadConfig()
        self.proxy = ProxyConfig()
        self.providers = ProviderConfig()
        self.reaction = ReactionConfig()
        self.bilibili = BilibiliConfig()
        self.debug = DebugConfig()
        self._parse()

    def _parse(self) -> None:
        trigger = self._raw.get("trigger", {}) or {}
        self.trigger = TriggerConfig(
            auto_parse=bool(trigger.get("auto_parse", True)),
            keywords=list(trigger.get("keywords", ["解析", "解析视频", "解析推文"])),
        )

        message = self._raw.get("message", {}) or {}
        self.message = MessageConfig(
            text_metadata=bool(message.get("text_metadata", True)),
            rich_media=bool(message.get("rich_media", True)),
        )

        download = self._raw.get("download", {}) or {}
        configured_cache_dir = str(download.get("cache_dir", "") or "").strip()
        if not configured_cache_dir:
            if os.path.exists('/.dockerenv'):
                cache_dir = "/app/sharedFolder/image_video_parser/cache"
            else:
                cache_dir = os.path.join(tempfile.gettempdir(), "astrbot_image_video_parser_cache")
        else:
            cache_dir = configured_cache_dir

        self.download = DownloadConfig(
            pre_download_all_media=bool(download.get("pre_download_all_media", True)),
            cache_dir=cache_dir,
        )

        proxy = self._raw.get("proxy", {}) or {}
        twitter_proxy = proxy.get("twitter", {}) or {}
        self.proxy = ProxyConfig(
            address=str(proxy.get("address", "") or "").strip(),
            twitter_use_parse_proxy=bool(twitter_proxy.get("parse", False)),
            twitter_use_image_proxy=bool(twitter_proxy.get("image", True)),
            twitter_use_video_proxy=bool(twitter_proxy.get("video", True)),
        )

        providers = self._raw.get("providers", {}) or {}
        self.providers = ProviderConfig(
            enable_twitter=bool(providers.get("twitter", True)),
            enable_douyin=bool(providers.get("douyin", True)),
            enable_bilibili=bool(providers.get("bilibili", True)),
        )

        reaction = self._raw.get("reaction", {}) or {}
        self.reaction = ReactionConfig(
            enabled=bool(reaction.get("enabled", True)),
            detect_emoji_id=str(reaction.get("detect_emoji_id", "265") or "265"),
            success_emoji=str(reaction.get("success_emoji", "👌") or "👌"),
            failed_emoji=str(reaction.get("failed_emoji", "😭") or "😭"),
            emoji_type=str(reaction.get("emoji_type", "1") or "1"),
        )

        bilibili = self._raw.get("bilibili", {}) or {}
        max_minutes_raw = bilibili.get("max_video_minutes", 0)
        try:
            max_minutes = int(max_minutes_raw)
        except (TypeError, ValueError):
            max_minutes = 0
        self.bilibili = BilibiliConfig(
            max_video_minutes=max(0, max_minutes),
            over_limit_message=str(
                bilibili.get("over_limit_message", "视频较长，请前往B站观看：{url}")
                or "视频较长，请前往B站观看：{url}"
            ),
        )

        debug = self._raw.get("debug", {}) or {}
        self.debug = DebugConfig(
            enabled=bool(debug.get("enabled", False)),
        )
