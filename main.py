import aiohttp

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core import ConfigManager
from .core.downloader import ensure_media_files
from .core.message_adapter import build_media_nodes, build_text_node
from .core.parser import ParserManager
from .core.parser.platform import TwitterXParser, DouyinParser
from .core.reaction import EmojiLikeReactor


@register(
    "astrbot_plugin_image_video_parser",
    "final",
    "解析插件（当前支持 X 与 Douyin 解析）",
    "1.0.0",
)
class ImageVideoParserPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.cfg = ConfigManager(config or {})
        self.debug_enabled = self.cfg.debug.enabled

        parsers = []

        if self.cfg.providers.enable_twitter:
            parsers.append(
                TwitterXParser(
                    use_parse_proxy=self.cfg.proxy.twitter_use_parse_proxy,
                    use_image_proxy=self.cfg.proxy.twitter_use_image_proxy,
                    use_video_proxy=self.cfg.proxy.twitter_use_video_proxy,
                    proxy_url=self.cfg.proxy.address or None,
                )
            )

        if self.cfg.providers.enable_douyin:
            parsers.append(DouyinParser())

        self.parser_manager = ParserManager(parsers) if parsers else None
        self.reactor = EmojiLikeReactor(
            enabled=self.cfg.reaction.enabled,
            detect_emoji_id=self.cfg.reaction.detect_emoji_id,
            success_emoji=self.cfg.reaction.success_emoji,
            failed_emoji=self.cfg.reaction.failed_emoji,
            emoji_type=self.cfg.reaction.emoji_type,
        )

    @filter.event_message_type(EventMessageType.ALL)
    async def auto_parse(self, event: AstrMessageEvent):
        """消息入口：识别链接、执行解析、发送媒体并反馈三态表情。"""
        if not self.cfg.message.has_any_output():
            return

        text = (event.message_str or "").strip()
        if not text:
            return

        if self.parser_manager is None:
            return

        links_with_parser = self.parser_manager.extract_all_links(text)
        if not links_with_parser:
            return

        await self.reactor.react_detected(event)

        if not self.cfg.trigger.should_parse(text):
            return

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            metadata_list = await self.parser_manager.parse_text(
                text,
                session,
                links_with_parser=links_with_parser,
            )

            any_success = False
            for metadata in metadata_list:
                if self.cfg.message.text_metadata:
                    text_node = build_text_node(metadata)
                    if text_node:
                        await event.send(event.chain_result([text_node]))

                file_paths = await ensure_media_files(
                    session,
                    metadata,
                    pre_download_all_media=self.cfg.download.pre_download_all_media,
                    cache_dir=self.cfg.download.cache_dir,
                )
                metadata["file_paths"] = file_paths

                sent_media = False
                if self.cfg.message.rich_media:
                    media_nodes = build_media_nodes(metadata, prefer_local=True)
                    if media_nodes:
                        try:
                            await event.send(event.chain_result(media_nodes))
                            sent_media = True
                        except Exception as e:
                            if self.debug_enabled:
                                logger.debug(f"本地媒体发送失败，回退URL发送: {e}")
                            fallback_nodes = build_media_nodes(metadata, prefer_local=False)
                            if fallback_nodes:
                                await event.send(event.chain_result(fallback_nodes))
                                sent_media = True
                    elif metadata.get("error"):
                        logger.warning(f"媒体节点为空，解析错误: {metadata.get('error')}")

                if sent_media:
                    any_success = True

            if any_success:
                await self.reactor.react_success(event)
            else:
                await self.reactor.react_failed(event)

    async def terminate(self):
        logger.info("astrbot_plugin_image_video_parser terminated")
