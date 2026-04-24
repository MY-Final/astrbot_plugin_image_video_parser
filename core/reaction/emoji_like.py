from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from astrbot.api import logger


class EmojiLikeReactor:
    """统一管理消息表情贴附，避免同一消息连续贴附抖动。"""

    def __init__(
        self,
        enabled: bool = True,
        detect_emoji_id: str = "265",
        success_emoji: str = "👌",
        failed_emoji: str = "😭",
        emoji_type: str = "1",
    ):
        self.enabled = enabled
        self.detect_emoji_id = str(detect_emoji_id)
        self.success_emoji = str(success_emoji)
        self.failed_emoji = str(failed_emoji)
        self.emoji_type = str(emoji_type)

        self._locks: dict[int, asyncio.Lock] = {}
        self._last_react_at: dict[int, float] = {}
        self._min_interval_sec = 0.8

    async def react_detected(self, event: Any) -> bool:
        """检测到可解析链接后贴检测态表情。"""
        return await self._react(event, self.detect_emoji_id)

    async def react_success(self, event: Any) -> bool:
        """解析流程完成且有媒体发送成功后贴成功态表情。"""
        return await self._react(event, self.success_emoji)

    async def react_failed(self, event: Any) -> bool:
        """解析流程完成但无媒体成功发送时贴失败态表情。"""
        return await self._react(event, self.failed_emoji)

    async def _react(self, event: Any, emoji: str) -> bool:
        if not self.enabled:
            return False

        message_id = self._extract_message_id(event)
        if message_id is None:
            return False

        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "set_msg_emoji_like"):
            return False

        emoji_id = self._normalize_emoji(emoji)
        if not emoji_id:
            return False

        lock = self._locks.setdefault(message_id, asyncio.Lock())
        async with lock:
            await self._wait_if_needed(message_id)

            ok = await self._set_msg_emoji_like(bot, message_id, emoji_id)
            if not ok:
                await asyncio.sleep(0.35)
                ok = await self._set_msg_emoji_like(bot, message_id, emoji_id)

            if ok:
                self._last_react_at[message_id] = time.monotonic()
            return ok

    async def _wait_if_needed(self, message_id: int) -> None:
        """同一条消息的连续贴附加最小间隔，减少平台侧状态闪烁。"""
        last = self._last_react_at.get(message_id)
        if last is None:
            return
        elapsed = time.monotonic() - last
        if elapsed < self._min_interval_sec:
            await asyncio.sleep(self._min_interval_sec - elapsed)

    async def _set_msg_emoji_like(self, bot: Any, message_id: int, emoji_id: str) -> bool:
        try:
            await bot.set_msg_emoji_like(
                message_id=message_id,
                emoji_id=emoji_id,
                emoji_type=self.emoji_type,
                set=True,
            )
            return True
        except Exception as e:
            logger.debug(f"set_msg_emoji_like failed: {e}")
            return False

    def _extract_message_id(self, event: Any) -> Optional[int]:
        """尽量从不同事件结构里提取 message_id。"""
        try:
            message_obj = getattr(event, "message_obj", None)
            raw = getattr(message_obj, "raw_message", None)
            if isinstance(raw, dict) and raw.get("message_id") is not None:
                return int(raw["message_id"])

            message_id = getattr(event, "message_id", None)
            if message_id is not None:
                return int(message_id)
        except Exception:
            return None
        return None

    @staticmethod
    def _normalize_emoji(emoji: str) -> str:
        """支持数字ID、#前缀和少量字符别名。"""
        val = str(emoji or "").strip()
        if not val:
            return ""
        if val.startswith("#"):
            val = val[1:].strip()
        if not val:
            return ""

        alias_map = {
            "👌": "124",
            "😭": "116",
        }
        if val.isdigit():
            return val
        return alias_map.get(val, "")
