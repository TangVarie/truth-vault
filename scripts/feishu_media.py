"""scripts/feishu_media.py — 按 file_token 把飞书多维表格里的一个附件下载到内存 (D-157, 首图试跑)。

用的是夜跑同步那个 FeishuClient 的 token 缓存 (sync_feishu_notes_to_truth_vault.FeishuClient._ensure_token),
凭证还是 FEISHU_APP_ID / FEISHU_APP_SECRET, 没有新的环境变量。

  · 地址只用 file_token 现拼 (drive/v1/medias/<token>/download), 不跟库里存的 url / tmp_url 走: 那两个字段只拿来
    取开了高级权限的表要带的 extra 参数, 而且只认 open.feishu.cn 这一个主机。
  · 流式读, 超过字节上限就断开, 不把整个文件读进来再量。
  · 不写盘。回的是 bytes, 调用方用完就丢。
  · 不打印、不抛出任何带 token / 链接 / 文件名 / 响应体的东西: 出错只抛 MediaError(状态词)。
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

MEDIA_URL = "https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
FEISHU_HOST = "open.feishu.cn"
CHUNK = 256 * 1024
TIMEOUT_S = 60
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")     # 只许这些字符: token 要拼进地址里

# 状态词 (只有这些会进日志和报告)
AUTH_FAILED = "auth_failed"            # 拿不到 tenant token: 凭证的问题
NO_PERMISSION = "no_permission"        # 400 / 403: 应用没有下载素材的权限, 或这张表要 extra
NOT_FOUND = "not_found"                # 404: 附件不在了
TOO_LARGE = "too_large"                # 超过字节上限
HTTP_ERROR = "http_error"              # 其它状态码
NETWORK = "network"                    # 超时 / 连不上
BAD_TOKEN = "bad_file_token"           # 库里的 file_token 不像一个 token


class MediaError(Exception):
    def __init__(self, status: str, detail: Optional[str] = None):
        super().__init__(status)
        self.status = status
        # 只给排查用的细项: HTTP 状态码、飞书回包里那个数字错误码、这次带没带 extra。只有字母数字和下划线,
        # 不带回包正文、地址、token。分得清「应用没开下载权限」和「这张表开了高级权限要 extra」。
        self.detail = detail


def _refusal_detail(resp: Any, status: int, had_extra: bool) -> str:
    code = "x"
    try:
        raw = b""
        for chunk in resp.iter_content(1024):
            raw += chunk or b""
            if len(raw) >= 4096:
                break
        import json as _json
        obj = _json.loads(raw[:4096].decode("utf-8", "replace"))
        c = obj.get("code") if isinstance(obj, dict) else None
        if isinstance(c, int) and not isinstance(c, bool) and 0 <= c < 10 ** 9:
            code = str(c)
    except Exception:  # noqa: BLE001 — 读不出来就算了, 细项只是锦上添花
        pass
    return f"http{status}_code{code}_extra{1 if had_extra else 0}"


def _extra_param(f: dict) -> Optional[str]:
    """库里存的 url / tmp_url 上要是带着 extra=…(高级权限的表), 取出来原样带上。只认飞书自己的主机。"""
    for key in ("url", "tmp_url"):
        raw = f.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            u = urlparse(raw)
        except ValueError:
            continue
        if u.scheme != "https" or u.hostname != FEISHU_HOST:
            continue
        vals = parse_qs(u.query).get("extra")
        if vals and vals[0]:
            return vals[0]
    return None


def download(client: Any, f: dict, max_bytes: int, *, http_get=None) -> bytes:
    """下载一个附件 (f 是 raw_extra 里的一个附件对象)。回 bytes; 任何失败抛 MediaError(状态词)。

    http_get: 测试注入用; 默认 requests.get。
    """
    token = f.get("file_token")
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise MediaError(BAD_TOKEN)
    if http_get is None:
        import requests
        http_get = requests.get
    params = {}
    extra = _extra_param(f)
    if extra:
        params["extra"] = extra
    for attempt in range(2):
        try:
            bearer = client._ensure_token()
        except Exception:  # noqa: BLE001 — FeishuClient 的报错里带着接口回的整个对象, 不能往外传
            raise MediaError(AUTH_FAILED) from None
        resp = None
        try:
            resp = http_get(MEDIA_URL.format(file_token=token), headers={"Authorization": f"Bearer {bearer}"},
                            params=params, stream=True, timeout=TIMEOUT_S)
            status = int(getattr(resp, "status_code", 0) or 0)
            if status in (400, 403):
                raise MediaError(NO_PERMISSION, _refusal_detail(resp, status, bool(extra)))
            if status == 401:
                if attempt == 0:
                    if hasattr(client, "_token"):
                        client._token = None
                    if hasattr(client, "_token_expires_at"):
                        client._token_expires_at = 0
                    continue
                raise MediaError(AUTH_FAILED)
            if status == 404:
                raise MediaError(NOT_FOUND)
            if status != 200:
                raise MediaError(HTTP_ERROR)
            buf = bytearray()
            for chunk in resp.iter_content(CHUNK):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise MediaError(TOO_LARGE)
            if not buf:
                raise MediaError(HTTP_ERROR)
            return bytes(buf)
        except MediaError:
            raise
        except Exception:  # noqa: BLE001 — requests 的报错里带着完整链接
            raise MediaError(NETWORK) from None
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:  # noqa: BLE001
                pass
    raise MediaError(AUTH_FAILED)
