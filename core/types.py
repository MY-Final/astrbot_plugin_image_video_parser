from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ParseResult:
    url: str
    title: str = ""
    author: str = ""
    desc: str = ""
    timestamp: str = ""
    platform: str = ""
    image_urls: List[List[str]] = None
    video_urls: List[List[str]] = None
    image_headers: Dict[str, str] = None
    video_headers: Dict[str, str] = None
    force_pre_download: bool = False
    error: str = ""
    use_image_proxy: bool = False
    use_video_proxy: bool = False
    proxy_url: Optional[str] = None
    duration_seconds: int = 0
    media_blocked_message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "desc": self.desc,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "image_urls": self.image_urls or [],
            "video_urls": self.video_urls or [],
            "image_headers": self.image_headers or {},
            "video_headers": self.video_headers or {},
            "force_pre_download": self.force_pre_download,
            "error": self.error,
            "use_image_proxy": self.use_image_proxy,
            "use_video_proxy": self.use_video_proxy,
            "proxy_url": self.proxy_url,
            "duration_seconds": self.duration_seconds,
            "media_blocked_message": self.media_blocked_message,
        }
