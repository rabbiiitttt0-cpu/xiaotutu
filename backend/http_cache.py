# -*- coding: utf-8 -*-
"""HTTP 条件请求(304) 工具

Starlette FileResponse 会自动带 ETag/Last-Modified，但不处理
If-None-Match / If-Modified-Since —— 浏览器缓存过期后拿旧 ETag 来重验，
服务端照样回 200 全量（1004 生产实测：17.7MB 字体、最大 72MB 的 DXF
全部原样重传一遍）。此模块在端点层补 304 协商：命中只回几百字节头。

用法（替代裸 FileResponse）：
    return cached_file_response(request, path, media_type=...,
                                cache_control="private, no-cache")

注意：必须走 cached_file_response——Starlette FileResponse 默认在 ASGI
__call__ 阶段才 stat 出 ETag/Last-Modified，构造后立即读 headers 是空的。
"""
import os
from email.utils import parsedate_to_datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import FileResponse, Response


def _etag_match(if_none_match: str, etag: str) -> bool:
    """If-None-Match 与 ETag 弱比较（去 W/ 前缀，支持 * 与逗号列表）"""
    if if_none_match.strip() == "*":
        return True
    target = etag.strip()
    if target.startswith("W/"):
        target = target[2:]
    for tag in if_none_match.split(","):
        tag = tag.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag == target:
            return True
    return False


def not_modified(request: Request, file_resp) -> Optional[Response]:
    """请求命中条件头 → 返回 304（沿用原响应的 ETag/Last-Modified/Cache-Control）；
    未命中 → None，端点照常返回原 FileResponse。"""
    if request.method != "GET":
        return None
    etag = file_resp.headers.get("etag")
    last_modified = file_resp.headers.get("last-modified")
    inm = request.headers.get("if-none-match")
    ims = request.headers.get("if-modified-since")
    hit = False
    if inm is not None and etag:
        hit = _etag_match(inm, etag)
    elif ims is not None and last_modified:
        # RFC 7232：有 If-None-Match 时以它为准，不再看 If-Modified-Since
        try:
            hit = (parsedate_to_datetime(ims).timestamp()
                   >= parsedate_to_datetime(last_modified).timestamp())
        except Exception:
            hit = False
    if not hit:
        return None
    headers = {}
    if etag:
        headers["etag"] = etag
    if last_modified:
        headers["last-modified"] = last_modified
    cc = file_resp.headers.get("cache-control")
    if cc:
        headers["cache-control"] = cc
    return Response(status_code=304, headers=headers)


def cached_file_response(request: Request, path, *, media_type=None,
                         headers=None, cache_control=None) -> Response:
    """FileResponse + 构造期 stat（拿到 ETag/Last-Modified）+ 条件请求 304。

    - cache_control：给则 setdefault 到响应（304 沿用同值）
    - 命中 If-None-Match/If-Modified-Since → 304；否则原 FileResponse
    """
    resp = FileResponse(str(path), media_type=media_type, headers=headers,
                        stat_result=os.stat(path))
    if cache_control:
        resp.headers.setdefault("Cache-Control", cache_control)
    return not_modified(request, resp) or resp
