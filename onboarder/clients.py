"""onboarder/clients.py — 自包含的飞书(REST)+ Supabase 客户端。

飞书客户端镜像 scripts/sync_feishu_notes_to_truth_vault.py 的 FeishuClient
(同一套 open.feishu.cn Bitable REST + tenant_access_token 缓存 + 401/5xx 重试),
刻意不 import scripts/ —— 与 librarian/ 同样的 deploy 独立性取舍(便于在 CI /
Railway 单独跑)。只读。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterator


class FeishuClient:
    """Minimal Feishu Bitable read-only client(镜像 scripts 版)。"""

    AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    RECORDS_URL = (
        "https://open.feishu.cn/open-apis/bitable/v1/apps/"
        "{app_token}/tables/{table_id}/records"
    )
    FIELDS_URL = (
        "https://open.feishu.cn/open-apis/bitable/v1/apps/"
        "{app_token}/tables/{table_id}/fields"
    )

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _ensure_token(self) -> str:
        import requests  # lazy

        if self._token and time.time() < self._expires_at - 60:
            return self._token
        r = requests.post(
            self.AUTH_URL,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")
        self._token = data["tenant_access_token"]
        self._expires_at = time.time() + data.get("expire", 7200)
        return self._token

    def _get_with_retry(self, url: str, headers: dict, params: dict, *, max_attempts: int = 3):
        import requests  # lazy

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                r = requests.get(url, headers=headers, params=params, timeout=30)
                if r.status_code == 401 and attempt == 0:
                    self._token = None
                    headers["Authorization"] = f"Bearer {self._ensure_token()}"
                    continue
                if 500 <= r.status_code < 600 and attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                return r
            except (requests.Timeout, requests.ConnectionError) as exc:  # type: ignore[attr-defined]
                last_exc = exc
                if attempt == max_attempts - 1:
                    raise
                time.sleep(2 ** attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError("_get_with_retry exhausted retries")

    def list_records(
        self, app_token: str, table_id: str, view_id: str | None = None, page_size: int = 100
    ) -> Iterator[dict[str, Any]]:
        """分页 yield 记录;每条至少含 record_id + fields(列名 → 值)。"""
        token = self._ensure_token()
        url = self.RECORDS_URL.format(app_token=app_token, table_id=table_id)
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"page_size": page_size}
        if view_id:
            params["view_id"] = view_id
        while True:
            r = self._get_with_retry(url, headers, params)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu list_records error: {data}")
            for item in data["data"].get("items", []):
                yield item
            if not data["data"].get("has_more"):
                break
            params["page_token"] = data["data"]["page_token"]
            time.sleep(0.1)

    def list_fields(self, app_token: str, table_id: str, page_size: int = 100) -> list[dict[str, Any]]:
        """列出表的所有字段(名称 + type + property,含单选/多选的 options)。"""
        token = self._ensure_token()
        url = self.FIELDS_URL.format(app_token=app_token, table_id=table_id)
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"page_size": page_size}
        out: list[dict[str, Any]] = []
        while True:
            r = self._get_with_retry(url, headers, params)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu list_fields error: {data}")
            out.extend(data["data"].get("items", []))
            if not data["data"].get("has_more"):
                break
            params["page_token"] = data["data"]["page_token"]
        return out


def feishu_from_env() -> FeishuClient:
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set")
    return FeishuClient(app_id, app_secret)


def pull_columns_and_samples(
    app_token: str, table_id: str, sample_n: int = 30, view_id: str | None = None
) -> dict[str, Any]:
    """拉前 sample_n 行 → 返回 {columns: [...], rows: [{...}], n: int}。

    columns = 样本行里出现过的所有列名的并集(空列可能漏 —— scaffold 取舍;
    需要 100% 列可加 app_table_field.list 端点,见 docs/16 待办)。
    """
    fs = feishu_from_env()
    rows: list[dict] = []
    columns: list[str] = []
    seen: set[str] = set()
    for item in fs.list_records(app_token, table_id, view_id=view_id, page_size=min(sample_n, 100)):
        fields = item.get("fields", {}) or {}
        for col in fields:
            if col not in seen:
                seen.add(col)
                columns.append(col)
        rows.append({"record_id": item.get("record_id"), "fields": fields})
        if len(rows) >= sample_n:
            break
    return {"columns": columns, "rows": rows, "n": len(rows)}


def _cell_to_str(v: Any):
    """飞书单元格 → 稳定字符串(单选=str;多选=list;有的字段是 dict / list[dict])。"""
    if v is None:
        return None
    if isinstance(v, list):
        parts = [str(x.get("text") or x.get("name") or x) if isinstance(x, dict) else str(x) for x in v]
        return " / ".join(p for p in parts if p) or None
    if isinstance(v, dict):
        return str(v.get("text") or v.get("name") or v)
    s = str(v).strip()
    return s or None


def list_fields(app_token: str, table_id: str) -> list[dict[str, Any]]:
    """字段元数据 [{field_name, type, options}]。单选/多选字段的 options = 枚举列的【完整】取值。"""
    out: list[dict[str, Any]] = []
    for f in feishu_from_env().list_fields(app_token, table_id):
        opts = ((f.get("property") or {}).get("options")) or []
        out.append({
            "field_name": f.get("field_name"),
            "type": f.get("type"),
            "options": [o.get("name") for o in opts if isinstance(o, dict)],
        })
    return out


def distinct_values(app_token: str, table_id: str, columns: list[str], max_scan: int = 50000) -> dict[str, Any]:
    """对 columns 做【全表】扫描,返回每列完整 distinct 取值 + 计数(枚举型列取全集,别靠样本)。"""
    from collections import Counter

    fs = feishu_from_env()
    counters: dict[str, Counter] = {c: Counter() for c in columns}
    n = 0
    for item in fs.list_records(app_token, table_id, page_size=100):
        fields = item.get("fields", {}) or {}
        for c in columns:
            if c in fields:
                s = _cell_to_str(fields[c])
                if s is not None:
                    counters[c][s] += 1
        n += 1
        if n >= max_scan:
            break
    return {"scanned": n, "distinct": {c: counters[c].most_common() for c in columns}}


def get_supabase():
    """service_role Supabase client(镜像 librarian/clients.py;dry-run 导入 / agent_runs 记录用,可选)。"""
    from supabase import create_client  # lazy

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


# ── Anthropic(中转站)单次调用 —— 镜像 librarian/clients.call_anthropic ──────
# 这是已验证能透传你中转站的那条路(非流式 messages.create + base_url)。
def parse_json(text: str):
    """剥掉 ``` 围栏再 json.loads;失败返回 None。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


def call_anthropic(prompt: str, model: str, *, system=None, max_tokens: int = 8000,
                   max_attempts: int = 4) -> str:
    """一次 Anthropic 调用 + 瞬时错误退避重试。lazy-import anthropic。

    走中转站:设了 ANTHROPIC_BASE_URL 就作为 base_url(api_key 用 ANTHROPIC_API_KEY),
    与 librarian / autowriter 同一约定;不设则走官方 endpoint。
    """
    import anthropic  # lazy

    kwargs: dict = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        kwargs["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("ANTHROPIC_BASE_URL"):
        kwargs["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    client = anthropic.Anthropic(**kwargs)
    for attempt in range(max_attempts):
        try:
            create_kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system is not None:
                create_kwargs["system"] = system
            msg = client.messages.create(**create_kwargs)
            return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status_code", None)
            transient = (
                status in (429, 500, 502, 503, 504, 529)
                or any(s in str(exc).lower() for s in (
                    "429", "500", "502", "503", "504", "529",
                    "timeout", "connection", "overloaded"))
            )
            if not transient or attempt == max_attempts - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("call_anthropic exhausted retries")
