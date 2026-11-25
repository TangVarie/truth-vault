"""已知格式的密钥打码 (2026-05-22 audit P3; 2026-11-25 S-09 从 _common.py 搬出来)。

只用标准库: 不连库、不装 supabase 的离线脚本 (gate1_* / gate2_* / onboarder/batch.py) 也能 import。
_common.py 原样转出 SECRET_PATTERNS 和 mask_secrets, 老的 `from _common import mask_secrets` 照常能用。

用法: 打印异常文本时写 print(f"... {mask_secrets(str(exc))}"), 不要直接 print(exc)。
CI 守卫 check_secret_masking.py §6 扫 scripts/ onboarder/ worker/ librarian/ 里漏包的 print。
"""
from __future__ import annotations

import re

# 已知 secret 前缀正则。加新格式时往这里加, 让 mask_secrets 覆盖所有 logger 和 print。
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),       # Anthropic
    re.compile(r"sb_secret_[A-Za-z0-9]{20,}"),       # Supabase 2024+
    re.compile(r"sbp_[A-Za-z0-9]{20,}"),             # Supabase service token
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),  # JWT
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),          # Google API key
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),      # OpenAI
    re.compile(r"sk-[A-Za-z0-9]{40,}"),              # OpenAI 老格式
]


def mask_secrets(s: str) -> str:
    """Mask known secret patterns in a string before logging it.

    Logger formatters / exception handlers / telemetry events should pipe
    user-visible strings through this before writing. Conservative — won't
    catch every secret shape, but catches Anthropic / Supabase / Google /
    OpenAI / JWT default formats.

    For exception messages from supabase-py / requests that may include
    bearer tokens in URLs or stacktrace, pass `mask_secrets(str(exc))`.
    """
    if not isinstance(s, str) or not s:
        return s
    for pat in SECRET_PATTERNS:
        s = pat.sub("***REDACTED***", s)
    return s
