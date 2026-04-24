# 解析插件

当前版本为聚合解析框架的第一步实现，已支持 **X(Twitter/X) 链接解析**。

## 当前能力

- 自动识别消息中的 X/Twitter 状态链接
- 解析文本元数据（标题/作者/简介/发布时间）
- 下载并发送图片/视频媒体
- 三态表情反馈（引用原消息贴附）
  - 检测到可解析链接：`#265`
  - 解析成功：`#👌`
  - 解析失败：`#😭`

## 配置说明（关键项）

- `providers.twitter`: 是否启用 X 解析
- `proxy.address`: 代理地址（示例：`http://127.0.0.1:7890`）
- `proxy.twitter.parse/image/video`: 解析/图片/视频代理开关
- `download.pre_download_all_media`: 是否预下载媒体（默认开启）
- `download.cache_dir`: 缓存目录（Docker 默认 `/app/sharedFolder/image_video_parser/cache`）
- `reaction.enabled`: 是否启用三态表情反馈
- `reaction.detect_emoji_id/success_emoji/failed_emoji`: 三态表情配置

## 说明

目前实现聚焦 X 解析，后续可在同一框架下继续扩展其它平台解析器。
