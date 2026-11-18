# SPDX-FileCopyrightText: 2026 烨染霜华
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporary HTTP URLs for images received as Base64."""

import asyncio
import base64
import re
import time
from contextlib import suppress
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request
from starlette.responses import Response

IMAGE_TTL_SECONDS = 3600
IMAGE_FILENAME = re.compile(r"[0-9a-f]{32}\.([a-z0-9](?:[a-z0-9.+-]{0,62}[a-z0-9])?)")


@cache
def image_directory() -> TemporaryDirectory[str]:
    return TemporaryDirectory(prefix="huimeng-images-")


def write_image(path: Path, encoded: str) -> None:
    image = base64.b64decode(encoded, validate=True)
    cutoff = time.time() - IMAGE_TTL_SECONDS
    for file in path.parent.iterdir():
        with suppress(FileNotFoundError, PermissionError):
            if file.stat().st_mtime <= cutoff:
                file.unlink()
    path.write_bytes(image)


async def publish_image(encoded: str, mime_type: str) -> str | None:
    subtype = mime_type.lower().removeprefix("image/")
    extension = "svg" if subtype == "svg+xml" else subtype
    filename = f"{uuid4().hex}.{extension}"
    if IMAGE_FILENAME.fullmatch(filename) is None:
        return None
    url = str(get_http_request().url_for("get_generated_image", filename=filename))
    try:
        path = Path(image_directory().name, filename)
        await asyncio.to_thread(write_image, path, encoded)
    except ValueError:
        return None
    except OSError:
        raise ToolError("保存生成的图片失败，无法提供下载链接。") from None
    return url


def read_image(path: Path) -> bytes:
    if path.stat().st_mtime <= time.time() - IMAGE_TTL_SECONDS:
        raise FileNotFoundError(path)
    return path.read_bytes()


async def get_generated_image(request: Request) -> Response:
    filename = request.path_params["filename"]
    match = IMAGE_FILENAME.fullmatch(filename)
    if match is None:
        return Response(status_code=404)
    path = Path(image_directory().name, filename)
    try:
        image = await asyncio.to_thread(read_image, path)
    except FileNotFoundError:
        return Response(status_code=404)
    media_type = "image/svg+xml" if match[1] == "svg" else f"image/{match[1]}"
    return Response(
        image,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )
