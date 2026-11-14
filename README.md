# 霜華绘梦 MCP

FastMCP 服务通过霜華 API 提供文生图、参考图生图、文生视频和图生视频。默认连接 `https://www.shapi.vip`，MCP 使用 Streamable HTTP。

作者：[烨染霜华](https://github.com/zhaibingye)

本项目版权归烨染霜华（2026）所有，按 GNU GPL 第 3 版或任何更高版本（`GPL-3.0-or-later`）发布。 [许可证全文](LICENSE)

## 启动

需要 Python 3.11+ 和 uv。在项目目录打开 PowerShell：

```powershell
uv sync --locked
uv run python server.py
```

MCP 地址为 `http://127.0.0.1:3005/mcp`。在支持 Streamable HTTP 的客户端填入这个 URL。例如，客户端的 JSON 配置可以写成：

```json
{
  "mcpServers": {
    "huimeng": {
      "url": "http://127.0.0.1:3005/mcp",
      "headers": {
        "Authorization": "Bearer <霜華 API 令牌>"
      }
    }
  }
}
```

每次调用工具时，MCP 从当前 HTTP 请求的 `Authorization` 头读取令牌，并通过 `Authorization: Bearer <Key>` 转发给霜華 API。客户端也可以把裸 Key 作为该头的值。视频查询时应使用提交任务的令牌。

通过 `--host` 和 `--port` 或 `MCP_HOST` 和 `MCP_PORT` 修改监听地址。

## 自定义上游地址

要让客户端按请求指定上游，编辑项目目录中的 `config.toml`，然后重启服务。

```toml
[gateway]
allow_url_header = true
```

在 MCP 客户端的 `headers` 中加入 `URL`，例如：

```json
{
  "Authorization": "Bearer <上游 API 令牌>",
  "URL": "https://gateway.example.com/v1"
}
```

`URL` 需要是完整的 HTTP(S) 地址，可以包含路径前缀，且不能带登录信息、查询参数或片段。末尾的 `/v1` 会自动移除，再拼接各工具的接口路径。视频任务的提交和查询应使用相同的上游地址。

开关关闭时会忽略 `URL` 请求头。开关开启但客户端省略 `URL` 时，也会使用服务端的默认地址。部署时可通过 `SHAPI_BASE_URL` 设置这个默认地址。令牌会发送到所选上游，请仅为受信任的客户端开启此功能。

## 工具

| 工具 | 参数和返回值 |
| --- | --- |
| `generate_image` | 传 `prompt`，可选 `provider`、`model`、`reference_images` 和 `options`。返回图片链接或 MCP 图片内容。SVG 以 MCP 嵌入资源返回。 |
| `generate_video` | 传 `prompt`，可选 `provider`、`model`、`duration_seconds`、`aspect_ratio`、`resolution` 和参考图。提交后返回 `provider`、`task_id` 和状态。 |
| `get_video_status` | 传提交时返回的 `provider` 和 `task_id`，间隔数秒查询。完成后返回 `video_url`，有尾帧时也返回 `last_frame_url`。 |
| `list_media_models` | 调用 `GET /v1/models`，列出当前令牌可见的生图和生视频系列模型。网关别名可以直接传给 `model`。 |

例如，调用 `generate_image` 时使用以下参数即可选择 GPT Image 2.6 Flare：

```json
{
  "provider": "openai",
  "model": "gpt-image-2.6-flare",
  "prompt": "一只纸折的白鹤飞过雨后的水面，黑白摄影",
  "options": {"size": "1536x1024", "quality": "high", "complexity": "medium"}
}
```

调用 `generate_video` 的示例：

```json
{
  "provider": "bytedance",
  "prompt": "镜头低空掠过雨后的水面，跟随飞行的纸鹤",
  "duration_seconds": 5,
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "options": {"return_last_frame": true}
}
```

图片参考输入使用 HTTP(S) URL 或图片 Base64 data URL。Google 生图使用 Base64 data URL，Google 视频的参考输入使用 PNG 或 JPEG data URL。用 `first_frame`、`last_frame` 和 `reference_images` 指定视频参考图，支持的组合由模型决定。网关返回的临时链接请在有效期内使用。图片调用建议给 MCP 客户端配置至少 300 秒的工具超时。

## 网关路径和默认模型

| 能力 | `provider` | 默认模型 | 霜華 API 路径 |
| --- | --- | --- | --- |
| 生图 | `openai` | `gpt-image-2.6-sunburst` | `POST /v1/images/generations`、`POST /v1/images/edits` |
| 生图 | `bytedance` | `doubao-seedream-5-5-261028` | `POST /api/v3/images/generations` |
| 生图 | `xai` | `grok-imagine-image-2.0` | `POST /v1/images/generations`、`POST /v1/images/edits` |
| 生图 | `google` | `gemini-nano-banana-2.1` | `POST /v1beta/models/{model}:generateContent` |
| 生视频 | `bytedance` | `doubao-seedance-2-5-260628` | `POST /api/v3/contents/generations/tasks`、`GET /api/v3/contents/generations/tasks/{id}` |
| 生视频 | `xai` | `grok-imagine-video-1.5` | `POST /v1/videos/generations`、`GET /v1/videos/{id}` |
| 生视频 | `google` | `gemini-omni-1.2-flash` | `POST /v1/videos`、`GET /v1/videos/{id}`，通过网关 Vertex AI 渠道 |

Google 视频通过网关的兼容接口提交。视频查询结果只有状态时，服务会查询 `GET /v1/tasks/{id}/artifacts` 获取可访问的链接。OpenAI 官方 Sora Videos API 已于 2026 年 9 月 24 日关闭。 [OpenAI 弃用公告](https://developers.openai.com/api/docs/deprecations#2026-03-24-sora-2-video-generation-models-and-videos-api)

文档参考

- [霜華 API 定价和模型目录](https://www.shapi.vip/pricing)（需登录）
- [OpenAI 生图](https://developers.openai.com/api/reference/resources/images/methods/generate) · [OpenAI 图像编辑](https://developers.openai.com/api/reference/resources/images/methods/edit)
- [xAI 生图和图像编辑](https://docs.x.ai/developers/rest-api-reference/inference/images#image-generation) · [xAI 视频](https://docs.x.ai/developers/rest-api-reference/inference/videos)
- [Gemini 生图](https://aistudio.google.com/docs/image-generation?generate-content=true) · [Gemini Omni 视频](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/omni-1-2-flash)
