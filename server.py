# SPDX-FileCopyrightText: 2026 烨染霜华
# SPDX-License-Identifier: GPL-3.0-or-later

"""FastMCP tools for image and video generation through Shapi."""

import argparse
import os
import re
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from gateway import (
    Options,
    Prompt,
    TaskID,
    first_http_url,
    image_data,
    image_input,
    provider_options,
    request_json,
)
from media import get_generated_image, publish_image

ImageProvider = Literal["openai", "bytedance", "xai", "google"]
VideoProvider = Literal["bytedance", "xai", "google"]

IMAGE_MODELS: dict[ImageProvider, str] = {
    "openai": "gpt-image-2.6-sunburst",
    "bytedance": "doubao-seedream-5-5-261028",
    "xai": "grok-imagine-image-2.0",
    "google": "gemini-nano-banana-2.1",
}
VIDEO_MODELS: dict[VideoProvider, str] = {
    "bytedance": "doubao-seedance-2-5-260628",
    "xai": "grok-imagine-video-1.5",
    "google": "gemini-omni-1.2-flash",
}
VIDEO_ROUTES: dict[VideoProvider, tuple[str, str]] = {
    "bytedance": ("/api/v3/contents/generations/tasks", "/api/v3/contents/generations/tasks"),
    "xai": ("/v1/videos/generations", "/v1/videos"),
    "google": ("/v1/videos", "/v1/videos"),
}
VIDEO_STATUS = {
    "queued": "queued",
    "pending": "running",
    "running": "running",
    "in_progress": "running",
    "succeeded": "succeeded",
    "completed": "succeeded",
    "done": "succeeded",
    "failed": "failed",
    "expired": "expired",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}
IMAGE_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}

mcp = FastMCP(
    "Huimeng",
    instructions=(
        "使用霜華 API 生成图片和视频。generate_image 返回图片 URL。"
        "generate_video 返回任务 ID，使用相同的 provider 和 task_id 调用 "
        "get_video_status 查询状态并获取视频 URL。"
    ),
    mask_error_details=True,
)
mcp.custom_route("/media/{filename}", methods=["GET"])(get_generated_image)


async def image_result(
    data: dict[str, Any], provider: ImageProvider, model: str, default_mime: str
) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    text: list[str] = []
    if provider == "google":
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("thought"):
                    continue
                blob = (
                    part.get("inlineData")
                    or part.get("inline_data")
                    or part.get("fileData")
                    or part.get("file_data")
                    or {}
                )
                mime = blob.get("mimeType") or blob.get("mime_type") or default_mime
                if blob and isinstance(mime, str) and mime.startswith("image/"):
                    images.append(
                        {
                            "url": blob.get("fileUri") or blob.get("file_uri"),
                            "b64_json": blob.get("data"),
                            "mime_type": mime,
                        }
                    )
                if part.get("text"):
                    text.append(part["text"])
    else:
        entries = data.get("data") or []
        if isinstance(entries, dict):
            entries = [entries]
        output_format = data.get("output_format")
        mime = (
            IMAGE_MIME.get(output_format, default_mime)
            if isinstance(output_format, str)
            else default_mime
        )
        for entry in entries:
            if isinstance(entry, dict):
                declared = entry.get("mime_type")
                media_type = (
                    declared
                    if isinstance(declared, str) and declared.startswith("image/")
                    else mime
                )
                images.append({**entry, "mime_type": media_type})

    files = []
    for image in images:
        url = first_http_url(image.get("url"))
        encoded = image.get("b64_json")
        if url is None and isinstance(encoded, str) and encoded:
            url = await publish_image(encoded, image["mime_type"])
        if url is not None:
            files.append({"url": url})

    if not files:
        feedback = data.get("promptFeedback") or {}
        reason = feedback.get("blockReason") or "响应中没有可用的图片 URL"
        raise ToolError(f"{provider} 生图失败：{reason}")

    result: dict[str, Any] = {"provider": provider, "model": model, "images": files}
    if text:
        result["text"] = "\n".join(text)
    usage = data.get("usageMetadata") or data.get("usage_metadata") or data.get("usage")
    if usage:
        result["usage"] = usage
    return result


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True})
async def generate_image(
    prompt: Prompt,
    provider: ImageProvider = "openai",
    model: Prompt | None = None,
    reference_images: list[str] | None = None,
    options: Options | None = None,
) -> dict[str, Any]:
    """文生图或参考图生图，在 images 中返回图片 URL。

    Args:
        prompt: 描述要生成的图片或要对参考图做的修改。
        provider: openai（GPT Image 2.6）、bytedance（Seedream）、xai（Grok）或 google（Nano Banana）。
        model: 霜華 API 接受的模型 ID。OpenAI 默认 gpt-image-2.6-sunburst，可传 gpt-image-2.6-flare。
        reference_images: HTTP(S) 图片链接或 Base64 图片 data URL。Google 使用 Base64 data URL。
        options: 模型原生选项。OpenAI 如 size、quality、output_format、complexity。Seedream 如 size、watermark。
            xAI 如 aspect_ratio、resolution、n。Google 使用 generationConfig 内的字段，如 imageConfig。
    """
    model = model or IMAGE_MODELS[provider]
    references = [image_input(image) for image in reference_images or []]
    params = provider_options(options, "model", "prompt", "image", "images", "contents")
    for field in ("stream", "deferred"):
        if params.get(field) is not None and params[field] is not False:
            raise ToolError(f"图片工具需要一次返回完整图片，请关闭 {field}。")

    if provider == "google":
        parts = [{"text": prompt}]
        for image in references:
            mime, data = image_data(image)
            parts.append({"inlineData": {"mimeType": mime, "data": data}})
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model):
            raise ToolError("Google model 需要填写模型 ID，例如 gemini-nano-banana-2.1。")
        config = {"responseModalities": ["IMAGE"], **params}
        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        data = await request_json(
            "POST",
            f"/v1beta/models/{model}:generateContent",
            payload=payload,
            timeout=300,
        )
        return await image_result(data, provider, model, "image/png")

    path = "/v1/images/edits" if references else "/v1/images/generations"
    payload = {"model": model, "prompt": prompt, **params}
    default_mime = "image/png"
    if provider == "bytedance":
        # The Ark route supports Seedream-specific options and uses one path for both modes.
        path = "/api/v3/images/generations"
        payload.setdefault("response_format", "url")
        if references:
            payload["image"] = references[0] if len(references) == 1 else references
        default_mime = "image/png" if model.startswith("doubao-seedream-5-5-") else "image/jpeg"
    elif provider == "xai":
        payload.setdefault("response_format", "url")
        if len(references) == 1:
            payload["image"] = {"url": references[0], "type": "image_url"}
        elif references:
            payload["images"] = [{"url": image} for image in references]
        default_mime = "image/jpeg"
    elif references:
        payload["images"] = [{"image_url": image} for image in references]

    output_format = payload.get("output_format")
    if isinstance(output_format, str):
        default_mime = IMAGE_MIME.get(output_format, default_mime)
    data = await request_json("POST", path, payload=payload, timeout=300)
    return await image_result(data, provider, model, default_mime)


def ark_image(url: str, role: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}, "role": role}


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True})
async def generate_video(
    prompt: Prompt,
    provider: VideoProvider = "bytedance",
    model: Prompt | None = None,
    duration_seconds: Annotated[int, Field(ge=-1, le=30)] | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    first_frame: str | None = None,
    last_frame: str | None = None,
    reference_images: list[str] | None = None,
    options: Options | None = None,
) -> dict[str, Any]:
    """提交文生视频或图生视频任务，返回 task_id。用 get_video_status 查询结果。

    Args:
        prompt: 描述画面、动作和运镜。
        provider: bytedance（Seedance）、xai（Grok）或 google（Gemini Omni）。
        model: 网关模型 ID。默认使用对应供应商的预设模型。
        duration_seconds: 视频秒数。部分 Seedance 模型接受 -1 自动选择。
        aspect_ratio: 宽高比，例如 16:9 或 9:16。
        resolution: 分辨率，例如 720p 或 1080p。
        first_frame: 首帧图片 URL 或 Base64 data URL。Google 使用 PNG/JPEG data URL。
        last_frame: 尾帧图片，格式同首帧。模型须支持此用法。
        reference_images: 参考图片，格式同首帧。
        options: 供应商原生扩展字段，例如 Seedance 的 generate_audio、watermark。
    """
    model = model or VIDEO_MODELS[provider]
    if duration_seconds == 0 or (duration_seconds == -1 and provider != "bytedance"):
        raise ToolError("请填写正整数时长。支持自动时长的 Seedance 模型可传 -1。")
    first = image_input(first_frame) if first_frame is not None else None
    last = image_input(last_frame) if last_frame is not None else None
    refs = [image_input(image) for image in reference_images or []]
    fields: dict[str, Any] = {"model": model}
    if resolution is not None:
        fields["resolution"] = resolution.lower()

    if provider == "bytedance":
        params = provider_options(options, "model", "prompt", "duration", "ratio", "resolution")
        extra_content = params.get("content", [])
        if not isinstance(extra_content, list) or any(
            not isinstance(item, dict) or item.get("type") == "text" for item in extra_content
        ):
            raise ToolError("options.content 可附加 Seedance 的非文本媒体输入。")
        content = [{"type": "text", "text": prompt}]
        if first:
            content.append(ark_image(first, "first_frame"))
        if last:
            content.append(ark_image(last, "last_frame"))
        content.extend(ark_image(image, "reference_image") for image in refs)
        if aspect_ratio is not None:
            fields["ratio"] = aspect_ratio
        if duration_seconds is not None:
            fields["duration"] = duration_seconds
        fields["content"] = content + extra_content
    elif provider == "xai":
        params = provider_options(
            options,
            "model",
            "prompt",
            "duration",
            "aspect_ratio",
            "resolution",
            "image",
            "last_frame",
            "reference_images",
        )
        fields["prompt"] = prompt
        if aspect_ratio is not None:
            fields["aspect_ratio"] = aspect_ratio
        if duration_seconds is not None:
            fields["duration"] = duration_seconds
        if first:
            fields["image"] = {"url": first}
        if last:
            fields["last_frame"] = {"url": last}
        if refs:
            fields["reference_images"] = [{"url": image} for image in refs]
    else:
        params = provider_options(
            options,
            "model",
            "prompt",
            "duration",
            "seconds",
            "size",
            "resolution",
            "image",
            "images",
            "input_reference",
        )
        if aspect_ratio not in (None, "16:9", "9:16"):
            raise ToolError("Google 视频的 aspect_ratio 须为 16:9 或 9:16。")
        if (last and not first) or (refs and (first or last)) or len(refs) in (1, 2):
            raise ToolError("Google 使用首帧、首尾帧或 3 至 6 张参考图。")
        if len(refs) > 6:
            raise ToolError("Google 最多使用 6 张参考图。")
        images = refs or [image for image in (first, last) if image]
        for image in images:
            mime, _ = image_data(image)
            if mime not in {"image/png", "image/jpeg"}:
                raise ToolError("Google 视频参考图须为 PNG 或 JPEG。")
        fields["prompt"] = prompt
        if duration_seconds is not None:
            fields["seconds"] = str(duration_seconds)
        if aspect_ratio is not None:
            # The gateway derives orientation from size and resolution from its own field.
            fields["size"] = "720x1280" if aspect_ratio == "9:16" else "1280x720"
        if images:
            fields["images"] = images

    submit_path, _ = VIDEO_ROUTES[provider]
    data = await request_json("POST", submit_path, payload={**params, **fields})
    task_id = data.get("request_id") or data.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise ToolError("网关响应缺少视频任务 ID，请先检查网关任务记录。")
    return {
        "provider": provider,
        "model": model,
        "task_id": task_id,
        "status": VIDEO_STATUS.get(data.get("status"), "queued"),
    }


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_video_status(provider: VideoProvider, task_id: TaskID) -> dict[str, Any]:
    """查询视频任务，成功后返回 video_url 和可用的 last_frame_url。provider 应与提交时一致。"""
    _, status_path = VIDEO_ROUTES[provider]
    data = await request_json("GET", f"{status_path}/{task_id}", timeout=30)
    status = VIDEO_STATUS.get(data.get("status"))
    if status is None:
        raise ToolError("网关返回了未知的视频任务状态。")

    result = {"provider": provider, "task_id": task_id, "status": status}
    for key in ("model", "progress", "error", "usage"):
        if data.get(key) is not None:
            result[key] = data[key]
    if status != "succeeded":
        return result

    content = data.get("content") or {}
    video = data.get("video") or {}
    metadata = data.get("metadata") or {}
    if video.get("respect_moderation") is False:
        result.update(status="failed", error={"message": "视频未通过上游内容审核。"})
        return result
    url = first_http_url(
        content.get("video_url"), video.get("url"), metadata.get("url"), data.get("video_url")
    )
    if url is None:
        artifacts = await request_json("GET", f"/v1/tasks/{task_id}/artifacts", timeout=30)
        url = first_http_url(
            *(
                item.get("content_url")
                for item in artifacts.get("artifacts") or []
                if isinstance(item, dict) and item.get("type") == "video"
            )
        )
    if url is not None:
        result["video_url"] = url
    else:
        result["message"] = "任务已完成，网关没有返回可用的视频链接。"
    last_frame_url = first_http_url(
        content.get("last_frame_url"), metadata.get("last_frame_url"), data.get("last_frame_url")
    )
    if last_frame_url is not None:
        result["last_frame_url"] = last_frame_url
    duration = data.get("duration") or video.get("duration") or data.get("seconds")
    if duration is not None:
        result["duration_seconds"] = duration
    return result


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_media_models() -> dict[str, Any]:
    """列出当前霜華 API Key 可见的已接入系列模型。"""
    response = await request_json("GET", "/v1/models", timeout=30)
    entries = response.get("data")
    if not isinstance(entries, list):
        raise ToolError("网关响应缺少模型列表。")
    model_ids = sorted(
        {
            entry["id"]
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
    )
    return {
        "image_models": [
            model
            for model in model_ids
            if model.startswith(
                ("gpt-image-", "chatgpt-image-", "doubao-seedream-", "grok-imagine-image")
            )
            or (model.startswith("gemini-") and ("-image" in model or "-banana-" in model))
        ],
        "video_models": [
            model
            for model in model_ids
            if model.startswith(("doubao-seedance-", "grok-imagine-video", "gemini-omni-"))
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="霜華绘梦 FastMCP 服务")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.getenv("MCP_PORT", "3005"))
    args = parser.parse_args()
    mcp.run(transport="http", host=args.host, port=args.port, path="/mcp", json_response=True)


if __name__ == "__main__":
    main()
