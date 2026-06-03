"""onboarder/clients.py — 自包含的飞书(REST)+ Supabase 客户端。

飞书客户端镜像 scripts/sync_feishu_notes_to_truth_vault.py 的 FeishuClient
(同一套 open.feishu.cn Bitable REST + tenant_access_token 缓存 + 401/5xx 重试),
刻意不 import scripts/ —— 与 librarian/ 同样的 deploy 独立性取舍(便于在 CI /
Railway 单独跑)。只读。
"""

from __future__ import annotations

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


def get_supabase():
    """service_role Supabase client(镜像 librarian/clients.py;dry-run 导入 / agent_runs 记录用,可选)。"""
    from supabase import create_client  # lazy

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)
