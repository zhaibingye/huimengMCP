# SPDX-FileCopyrightText: 2026 烨染霜华
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP transport and shared validation for Shapi tools."""

import base64
import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from pydantic import JsonValue, StringConstraints

DEFAULT_BASE_URL = "https://www.shapi.vip"

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Options = dict[str, JsonValue]
TaskID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]*$", max_length=200)]
DATA_IMAGE = re.compile(r"data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/]+={0,2})")
AUTHORIZATION = re.compile(r"(?:Bearer +)?([A-Za-z0-9._~+/-]+=*)", re.IGNORECASE | re.ASCII)


def load_allow_url_header(config_path: Path) -> bool:
    try:
        with config_path.open("rb") as config_file:
            gateway = tomllib.load(config_file).get("gateway", {})
    except FileNotFoundError:
        return False
    if not isinstance(gateway, dict):
        raise TypeError("config.toml 中的 [gateway] 须为 TOML 表。")
    enabled = gateway.get("allow_url_header", False)
    if not isinstance(enabled, bool):
        raise TypeError("config.toml 中的 gateway.allow_url_header 须为 true 或 false。")
    return enabled


ALLOW_URL_HEADER = load_allow_url_header(Path(__file__).with_name("config.toml"))


def http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def image_data(value: str) -> tuple[str, str]:
    match = DATA_IMAGE.fullmatch(value)
    if match is None:
        raise ToolError("参考图需要使用 data:image/...;base64,... 格式。")
    mime_type, data = match.groups()
    try:
        base64.b64decode(data, validate=True)
    except ValueError:
        raise ToolError("参考图的 Base64 数据无效。") from None
    return mime_type, data


def image_input(value: str) -> str:
    if not http_url(value):
        image_data(value)
    return value


def provider_options(options: Options | None, *reserved: str) -> Options:
    options = options or {}
    conflicts = sorted(options.keys() & set(reserved))
    if conflicts:
        raise ToolError(f"options 不能设置这些字段：{', '.join(conflicts)}")
    return options


def request_api_key() -> str:
    error = "请通过 MCP HTTP 请求头 Authorization: Bearer <霜華 API Key> 提供令牌。"
    try:
        values = get_http_request().headers.getlist("authorization")
    except RuntimeError:
        raise ToolError(error) from None
    if len(values) != 1:
        raise ToolError(error)
    value = values[0].strip()
    match = AUTHORIZATION.fullmatch(value)
    if not match or value.lower() == "bearer":
        raise ToolError(error)
    return match[1]


def normalize_base_url(value: str, source: str) -> str:
    base_url = value.strip().rstrip("/")
    error = f"{source} 须为完整的 HTTP(S) 地址，且不带登录信息、查询参数或片段。"
    if not http_url(base_url) or any(char in base_url for char in "?#\\"):
        raise ToolError(error)
    try:
        port = httpx.URL(base_url).port
    except httpx.InvalidURL:
        raise ToolError(error) from None
    if port is not None and not 1 <= port <= 65535:
        raise ToolError(error)
    if urlsplit(base_url).path.endswith("/v1"):
        return base_url.removesuffix("/v1")
    return base_url


def request_base_url() -> str:
    if ALLOW_URL_HEADER:
        values = get_http_request().headers.getlist("url")
        if len(values) > 1:
            raise ToolError("请只提供一个 URL 请求头。")
        if values:
            return normalize_base_url(values[0], "URL 请求头")

    base_url = os.getenv("SHAPI_BASE_URL", DEFAULT_BASE_URL)
    return normalize_base_url(base_url, "SHAPI_BASE_URL")


async def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    key = request_api_key()
    base_url = request_base_url()
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10),
            follow_redirects=False,
        ) as client:
            response = await client.request(method, base_url + path, headers=headers, json=payload)
    except httpx.TimeoutException:
        if method == "POST":
            raise ToolError("等待霜華 API 超时。请求可能已被接受，请先检查网关记录。") from None
        raise ToolError("查询霜華 API 超时，可以重新查询。") from None
    except httpx.RequestError:
        raise ToolError("连接上游 API 失败，请检查网络和上游地址。") from None

    try:
        data = response.json()
    except ValueError:
        data = None

    body = data if isinstance(data, dict) else {}
    error = body.get("error")
    if not response.is_success or (error and not body.get("status")):
        message = error.get("message") if isinstance(error, dict) else error
        message = message or body.get("message") or "网关未返回错误详情。"
        message = str(message).replace(key, "[REDACTED]")[:500]
        request_id = response.headers.get("x-oneapi-request-id")
        suffix = f"（请求 ID {request_id}）" if request_id else ""
        raise ToolError(f"霜華 API HTTP {response.status_code}：{message}{suffix}")
    if not isinstance(data, dict):
        raise ToolError(f"霜華 API 返回了非 JSON 对象（HTTP {response.status_code}）。")
    return data
