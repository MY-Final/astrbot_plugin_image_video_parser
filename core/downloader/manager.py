from __future__ import annotations

import os
import hashlib
from typing import Any, Dict, List

import aiohttp


def _name_from_content_type(content_type: str, fallback: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "image/jpeg":
        return f"{fallback}.jpg"
    if ct == "image/png":
        return f"{fallback}.png"
    if ct == "image/webp":
        return f"{fallback}.webp"
    if ct == "video/mp4":
        return f"{fallback}.mp4"
    return fallback


async def download_to_cache(
    session: aiohttp.ClientSession,
    cache_dir: str,
    url: str,
    headers: Dict[str, str] | None = None,
    proxy: str | None = None,
    fallback_name: str = "media.bin",
) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    async with session.get(
        url,
        headers=headers or {},
        timeout=aiohttp.ClientTimeout(total=60),
        proxy=proxy,
    ) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        filename = _name_from_content_type(content_type, fallback_name)
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        if "." in filename:
            base, ext = filename.rsplit(".", 1)
            filename = f"{base}_{digest}.{ext}"
        else:
            filename = f"{filename}_{digest}"
        path = os.path.join(cache_dir, filename)
        data = await resp.read()
        with open(path, "wb") as f:
            f.write(data)
        return path


async def ensure_media_files(
    session: aiohttp.ClientSession,
    metadata: Dict[str, Any],
    pre_download_all_media: bool,
    cache_dir: str,
) -> List[str]:
    file_paths: List[str] = []

    image_headers = metadata.get("image_headers", {}) or {}
    video_headers = metadata.get("video_headers", {}) or {}

    image_proxy = metadata.get("proxy_url") if metadata.get("use_image_proxy") else None
    video_proxy = metadata.get("proxy_url") if metadata.get("use_video_proxy") else None

    if pre_download_all_media:
        for idx, image_url_list in enumerate(metadata.get("image_urls", []) or []):
            if not image_url_list:
                continue
            path = await download_to_cache(
                session,
                cache_dir,
                image_url_list[0],
                headers=image_headers,
                proxy=image_proxy,
                fallback_name=f"astr_img_{idx}",
            )
            file_paths.append(path)

    need_video_pre_download = bool(metadata.get("force_pre_download") or pre_download_all_media)
    if need_video_pre_download:
        for idx, video_url_list in enumerate(metadata.get("video_urls", []) or []):
            if not video_url_list:
                continue
            path = await download_to_cache(
                session,
                cache_dir,
                video_url_list[0],
                headers=video_headers,
                proxy=video_proxy,
                fallback_name=f"astr_video_{idx}",
            )
            file_paths.append(path)

    return file_paths
