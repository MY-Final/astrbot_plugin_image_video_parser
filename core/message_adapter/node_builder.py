from __future__ import annotations

import os
from typing import Any, Dict, List

from astrbot.api.message_components import Plain, Image, Video


def build_text_node(metadata: Dict[str, Any]) -> Plain | None:
    parts: List[str] = []
    if metadata.get("title"):
        parts.append(f"标题：{metadata['title']}")
    if metadata.get("author"):
        parts.append(f"作者：{metadata['author']}")
    if metadata.get("desc"):
        parts.append(f"简介：{metadata['desc']}")
    if metadata.get("timestamp"):
        parts.append(f"发布时间：{metadata['timestamp']}")
    if metadata.get("url"):
        parts.append(f"原始链接：{metadata['url']}")
    if metadata.get("error"):
        parts.append(f"解析失败：{metadata['error']}")
    if not parts:
        return None
    return Plain("\n".join(parts))


def build_media_nodes(metadata: Dict[str, Any], prefer_local: bool = True) -> List[Any]:
    nodes: List[Any] = []
    file_paths = metadata.get("file_paths", []) or []

    local_images = [p for p in file_paths if os.path.splitext(p)[1].lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    local_videos = [p for p in file_paths if os.path.splitext(p)[1].lower() in {".mp4", ".mov", ".mkv"}]

    if prefer_local:
        for p in local_images:
            if os.path.exists(p):
                nodes.append(Image.fromFileSystem(p))
        for p in local_videos:
            if os.path.exists(p):
                nodes.append(Video.fromFileSystem(p))

    if not nodes:
        for group in metadata.get("image_urls", []) or []:
            if group:
                nodes.append(Image.fromURL(group[0]))
        for group in metadata.get("video_urls", []) or []:
            if group:
                nodes.append(Video.fromURL(group[0]))

    return nodes
