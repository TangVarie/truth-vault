"""
sync_feishu_notes_to_truth_vault.py
═══════════════════════════════════════════════════════════════════════════

把指定项目的飞书多维表格数据 sync 到 truth_vault.notes。

用法:
    python sync_feishu_notes_to_truth_vault.py NUC_phase1
    python sync_feishu_notes_to_truth_vault.py NRT_phase3 --dry-run
    python sync_feishu_notes_to_truth_vault.py NUC_phase1 --limit 10

环境变量:
    SUPABASE_URL                    （共享 Supabase 实例 URL）
    SUPABASE_SERVICE_ROLE_KEY       （service_role，绕过 RLS）
    FEISHU_APP_ID                   （飞书应用 ID）
    FEISHU_APP_SECRET               （飞书应用 Secret）

mapping yaml 必须包含 sync_config 段提供飞书表定位:
    sync_config:
      feishu_app_token: bascnXXXXXXXXXXXXX
      feishu_table_id:  tblXXXXXXXXXX
      feishu_view_id:   vewXXXXXXXXXX   # 可选；不填用 default view

幂等性:
    note_id 是 PRIMARY KEY (= f"{project_id}_{feishu_record_id}")，
    使用 UPSERT (insert ... on_conflict='note_id') 重跑安全。
    指标会重新写一份 metric_snapshot（window_label='ad_hoc'），
    UNIQUE(note_id, window_label, source='feishu_import') 防重复。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Iterator

import requests
from supabase import Client

from _common import (
    ensure_account_exists,
    ensure_project_exists,
    extract_tier,
    get_supabase_client,
    load_mapping,
    make_note_id,
    map_intent,
    parse_array,
    parse_numeric,
    parse_feishu_date,
    parse_audience_analysis,
    quarantine_record,
    setup_logger,
    update_project_date_range,
    _direction_key,
    _iso_now,
)


logger = setup_logger("sync_feishu_notes")


# ═════════════════════════════════════════════════════════════════════════
# Feishu Bitable client
# ═════════════════════════════════════════════════════════════════════════

class FeishuClient:
    """Minimal Feishu Bitable read-only client.

    Caches tenant_access_token until it expires.  Not thread-safe, single
    process only.  For higher throughput see Feishu Open API rate limits
    (default 50 QPS per app for Bitable read).
    """

    AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    BITABLE_RECORDS_URL = (
        "https://open.feishu.cn/open-apis/bitable/v1/apps/"
        "{app_token}/tables/{table_id}/records"
    )

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
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
        self._token_expires_at = time.time() + data.get("expire", 7200)
        return self._token

    def _get_with_retry(
        self,
        url: str,
        headers: dict,
        params: dict,
        *,
        max_attempts: int = 3,
    ) -> "requests.Response":
        """GET with bounded retries on transient errors.

        Retry policy:
          - 401 → refresh token, retry once (existing behavior)
          - 5xx, Timeout, ConnectionError → exponential backoff 1/2/4s, max 3 tries
          - Other 4xx (404 / 422 / etc) → return immediately, caller raises

        NOTE: mutates `headers` in place when refreshing the bearer token
        on 401. The caller (list_records) shares ONE headers dict across all
        pagination requests; updating in place ensures every subsequent page
        uses the fresh token instead of hitting 401 → reauth on each page.
        Don't pass a dict you need preserved as-is.
        """
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                r = requests.get(url, headers=headers, params=params, timeout=30)
                if r.status_code == 401 and attempt == 0:
                    # token expired mid-pagination; refresh and retry once.
                    # Mutate caller's headers dict in place so subsequent
                    # pages also pick up the new token (codex review
                    # discussion_r3286292885 PR #12).
                    self._token = None
                    new_token = self._ensure_token()
                    headers["Authorization"] = f"Bearer {new_token}"
                    continue
                if 500 <= r.status_code < 600:
                    if attempt == max_attempts - 1:
                        return r  # let caller raise via raise_for_status
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                return r
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt == max_attempts - 1:
                    raise
                wait = 2 ** attempt
                time.sleep(wait)
        # Unreachable: above loop either returns or raises
        if last_exc:
            raise last_exc
        raise RuntimeError("_get_with_retry exhausted retries without raising")

    def list_records(
        self,
        app_token: str,
        table_id: str,
        view_id: str | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Yield records from a Feishu Bitable, paginating through all pages.

        Each yielded dict has at least:
            record_id: str         (飞书自动 ID, used as feishu_record_id)
            fields: dict           (列名 → 单元格值; 飞书 API 原生格式)

        2026-05-22 audit P1: GET 在 5xx / 网络异常时, 老代码直接 raise_for_status,
        飞书侧瞬时抖动会中断整个 sync. 加 _get_with_retry: 401 刷 token (一次),
        5xx / Timeout / ConnectionError 指数退避 (1/2/4s), 最多 3 次.
        硬性 4xx (404 / 422) 仍 fail-fast 因为重试也是同样错.
        """
        token = self._ensure_token()
        url = self.BITABLE_RECORDS_URL.format(app_token=app_token, table_id=table_id)
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
            # gentle rate limit
            time.sleep(0.1)


# ═════════════════════════════════════════════════════════════════════════
# Mapping-driven row transformation
# ═════════════════════════════════════════════════════════════════════════

# R-031: autowriter 回灌 lineage 列 (docs/11 「lineage 元数据列」). autowriter "AI 写 →
# 人工审 → 发布 → 飞书回收" 闭环里, 飞书表带 6 个 _source_autowriter_* / _ai_engine /
# _exported_at 列。这些列必须:
#   (a) 被【声明】, 否则 D-021 把每条带它们的行整行 quarantine (拖垮 ingestion);
#   (b) 其中两个 UUID → 提升进 notes 的跨 schema FK 列 source_autowriter_item_id /
#       source_autowriter_version_id (schema 已有, UUID), 这样 v_model_comparison /
#       v_prompt_performance 才 JOIN 得到 autowriter.versions 出模型对比;
#   (c) 其余 4 列 (project/batch id · ai_engine · exported_at) 留 raw_extra 留痕。
# 列名固定 (不进 field_mapping, 按名特殊处理), 故对【所有】项目预声明、与具体 mapping 无关。
_LINEAGE_FK_COLS = {
    "_source_autowriter_item_id":    "source_autowriter_item_id",
    "_source_autowriter_version_id": "source_autowriter_version_id",
}
_LINEAGE_RAW_EXTRA_COLS = (
    "_source_autowriter_project_id",
    "_source_autowriter_batch_id",
    "_ai_engine",
    "_exported_at",
)
_LINEAGE_COLS = tuple(_LINEAGE_FK_COLS) + _LINEAGE_RAW_EXTRA_COLS

# 判"空占位行"用: 一条缺 raw_content 的行, 若【没有任何 note-like 实质信号】(账号/链接/曝光/
# 阅读/互动/tier), 就不是真笔记, 而是飞书多维表格的占位行或评论碎片行(只有 父记录链接 / 随贴评论 /
# 发布时间 / 蓝词 等)。NUC_1 实测这类 445 行(纯父记录占位 + 评论碎片), 每轮逐条 WARNING 刷屏无意义
# → 静默计数、收尾出一行汇总。反之: 有这些信号却缺 raw_content = 真数据异常(本该是笔记却丢了正文)
# → 仍逐条 WARNING。注: 发布时间/蓝词记录【不】算 note-like 信号(评论碎片也常带), 故不在此列。
_NOTE_DATA_SIGNALS = (
    "account_id", "publish_url", "impressions", "reads", "interactions", "tier",
)


def _skip_on_demand_on_cron(sync_interval: str | None, scheduled: bool) -> bool:
    """夜间 cron(scheduled=True)是否应跳过该项目。

    sync_interval=on_demand 的项目【只】在显式 dispatch / 改成 daily 后才进夜间 cron ——
    防新接的表(填了飞书坐标但还没 preflight 验证)被 02:00 cron 自动灌、把未声明列的真内容行
    quarantine(codex PR#67 review)。on_demand 是 onboarder 起草的安全默认: 接表填坐标 →
    preflight → 显式跑验证 → 改 daily 入 cron。保守: 只有【确实 cron】且【确实 on_demand】才跳,
    显式 dispatch / 本地手跑(scheduled=False)照跑(不挡人工操作)。
    """
    return scheduled and sync_interval == "on_demand"


def transform_row(
    mapping: dict,
    feishu_record_id: str,
    raw_fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Transform a Feishu row into:
        - note_dict: row ready for truth_vault.notes UPSERT
        - metric_dict: row ready for truth_vault.metric_snapshots INSERT (or None)
        - undeclared_fields: column names not in field_mapping AND not in
          project_specific_fields_to_raw_extra; trigger quarantine if non-empty.
    """
    field_mapping = mapping["field_mapping"]
    fields_to_raw_extra = set(mapping.get("project_specific_fields_to_raw_extra", []))
    # _LINEAGE_COLS (R-031) 全局预声明 → 飞书表加 autowriter 回灌列时不再整行 quarantine。
    declared = set(field_mapping.keys()) | fields_to_raw_extra | set(_LINEAGE_COLS)

    # Allow control fields that are always present in Feishu API responses
    # but not user-defined columns
    ignored_meta_keys = {"_record_id", "_created_time", "_last_modified_time"}

    undeclared: list[str] = [
        col for col in raw_fields.keys()
        if col not in declared and col not in ignored_meta_keys
    ]

    note: dict[str, Any] = {
        "note_id": make_note_id(mapping["project_id"], feishu_record_id),
        "project_id": mapping["project_id"],
        "platform": mapping.get("platform", "xiaohongshu"),
        "feishu_record_id": feishu_record_id,
        # ingested_at intentionally NOT set here. The schema sets
        # DEFAULT NOW() on insert, and a BEFORE UPDATE trigger
        # (preserve_ingested_at) reverts it on every UPSERT-as-update.
        # Setting it client-side would let the trigger silently overwrite
        # what we send, which is wasteful and confusing.
    }
    intermediates: dict[str, Any] = {}
    raw_extra: dict[str, Any] = {}

    for feishu_col, schema_target in field_mapping.items():
        if feishu_col not in raw_fields:
            continue
        value = raw_fields[feishu_col]
        if schema_target.startswith("_"):
            intermediates[schema_target] = value
        else:
            note[schema_target] = _coerce_value(schema_target, value)

    # ── computed_fields: 合成数值列(早期表无单一「互动量」, 只有 点赞/收藏/分享/评论 分列)──
    #   yaml:  computed_fields: { interactions: { sum: [点赞数, 收藏数, 分享数, 评论数] } }
    # 把多列 parse_numeric 后求和写进目标数值列 —— 支持 TGV 这类无聚合互动量的表做 数值推断
    # tier + 看板互动展示。注意:① 源列仍须在 field_mapping/raw_extra 声明(否则 D-021 整行
    # quarantine), 求和只读不消费, 源分项照常进 raw_extra 留痕;② 仅当目标列【还没被 field_mapping
    # 显式赋值】时才写, 不覆盖直接映射的真值;③ 全空 → 不写(保持 None, 不写 0 冒充有数据)。
    for target_col, spec in (mapping.get("computed_fields") or {}).items():
        if not isinstance(spec, dict) or not spec.get("sum"):
            continue
        if note.get(target_col) is not None:
            continue
        total, seen = 0.0, False
        for src_col in spec["sum"]:
            v = parse_numeric(raw_fields.get(src_col))
            if v is not None:
                total += v
                seen = True
        if seen:
            note[target_col] = int(total) if target_col in _NUMERIC_COLS else total

    # Project-specific allowlist → raw_extra
    for feishu_col in fields_to_raw_extra:
        if feishu_col in raw_fields:
            raw_extra[feishu_col] = raw_fields[feishu_col]
    if raw_extra:
        note["raw_extra"] = raw_extra

    # ── R-031: autowriter 回灌 lineage 列 → FK 列 + raw_extra ──
    # 两个 UUID 列提升进 notes 的跨 schema FK 列 (UUID 字符串直接写; 用 _direction_key 把飞书
    # 富文本 list[dict{text}] / 单选 dict 展平成纯串, 同其它 cell 的处理)。其余 4 列留 raw_extra。
    for feishu_col, fk_col in _LINEAGE_FK_COLS.items():
        if feishu_col in raw_fields:
            uuid_val = _direction_key(raw_fields[feishu_col]).strip()
            if uuid_val:
                note[fk_col] = uuid_val
    for feishu_col in _LINEAGE_RAW_EXTRA_COLS:
        if feishu_col in raw_fields and raw_fields[feishu_col] not in (None, "", []):
            note.setdefault("raw_extra", {})[feishu_col] = raw_fields[feishu_col]

    # ── Secondary processing per mapping ──
    consumed_intermediates: set[str] = set()

    # tier_extraction: A/B families map 「状态」→ _status_raw; C family (TGV/QSHG)
    # maps 「备注」→ _note_for_tier. Pick the intermediate based on the yaml's
    # `tier_extraction.source` ("状态字段" or "备注字段"). Bug fix: previously
    # only _status_raw was checked, which silently dropped tier for C-family
    # projects (TGV_1's 47 「新爆」 records would end up tier=NULL).
    tier_extraction = mapping.get("tier_extraction") or {}
    tier_source = tier_extraction.get("source", "状态字段")
    tier_intermediate_key = (
        "_note_for_tier" if tier_source == "备注字段" else "_status_raw"
    )
    if tier_intermediate_key in intermediates and tier_extraction.get("rules"):
        note["tier"] = extract_tier(
            intermediates[tier_intermediate_key],
            tier_extraction["rules"],
        )
        # Track tier_source so downstream views can distinguish 状态字段 vs 备注字段
        # vs 数值推断 (the latter still TODO — see numeric fallback).
        note["tier_source"] = tier_source
        consumed_intermediates.add(tier_intermediate_key)
    if "_intent_raw" in intermediates and "intent_mapping" in mapping:
        note["intent"] = map_intent(
            intermediates["_intent_raw"],
            mapping["intent_mapping"],
        )
        consumed_intermediates.add("_intent_raw")
    # 方向级 tier 阈值覆盖(单方向配置可选, docs/04 Step 3)。默认 None → 数值兜底用项目级。
    dir_threshold_override = None
    if "_direction_raw" in intermediates:
        raw_dir = intermediates["_direction_raw"]
        # Always keep the raw value in raw_extra for traceability/annotation
        note.setdefault("raw_extra", {})["_direction_raw"] = raw_dir
        consumed_intermediates.add("_direction_raw")
        # Feishu may return 方向 as a list (multi-select / rich-text segments);
        # flatten to a hashable string for the dict-key lookups below.
        dir_key = _direction_key(raw_dir)

        # Apply the deterministic portion of direction_decomposition. For
        # single-direction configs (no sub_directions), we can lift
        # content_format / target_audience / user_pain_point / product_focus
        # and intent_override straight from the yaml — no LLM needed. Configs
        # with sub_directions (NUC_phase1's nutritional / surgery branches)
        # still require LLM sub-classification and are skipped here; the
        # raw direction stays in raw_extra so an annotation pass can resolve
        # it. excluded_directions is honored as 'quarantine via tier_source'.
        decomposition = (mapping.get("direction_decomposition") or {}).get(dir_key)
        if decomposition is not None and "sub_directions" not in decomposition:
            for col in ("content_format", "target_audience",
                        "user_pain_point", "product_focus"):
                val = decomposition.get(col)
                if val is not None and col not in note:
                    note[col] = val
            if decomposition.get("intent_override") is not None:
                note["intent"] = decomposition["intent_override"]

        # 方向级 tier_threshold_override: 与有没有 sub_directions 无关(它是【方向级】阈值)——
        # 单方向 AND NUC 式粗方向(含 sub_directions)都该 honor, 故放 sub_directions 守卫【外面】。
        # 只有 content_format/audience 等确定性 lift 才依赖单方向(codex PR#60 review)。
        # 形如 {爆: N, 大爆: M}(可部分)—— 下方数值兜底用它盖项目级 tier_thresholds。
        if decomposition and isinstance(decomposition.get("tier_threshold_override"), dict):
            dir_threshold_override = decomposition["tier_threshold_override"]

        # Honor excluded_directions (NRT_phase3's "女性自发, 男性自发" anomaly):
        # mark as data-anomalous so downstream training queries filter it out
        # without losing the row.
        for excluded in (mapping.get("excluded_directions") or []):
            if excluded.get("direction") == dir_key:
                note["tier"] = "数据异常"
                note["tier_source"] = "数据异常"
                break

    # ── Numeric tier fallback (Gap 1) ──
    # When no text-based rule fired (tier is None) OR the status mapped to
    # the placeholder "未知" (e.g. NUC's "评估中" → "未知"), assign a tier by
    # threshold if interactions data already shows a clear hit. Without the
    # "未知" check, an operator-pending row whose data already qualifies for
    # 爆/大爆 would stay 未知 forever and never reach the flywheel downstream.
    # tier_source is overwritten to '数值推断' only when we actually promote.
    existing_tier = note.get("tier")
    if existing_tier in (None, "未知") and note.get("interactions") is not None:
        # 项目级阈值, 被该方向的 tier_threshold_override 覆盖(方向级 > 项目级)。
        thresholds = dict(mapping.get("tier_thresholds") or {})
        if dir_threshold_override:
            thresholds.update(dir_threshold_override)
        n_interactions = note["interactions"]
        if "大爆" in thresholds and n_interactions >= thresholds["大爆"]:
            note["tier"] = "大爆"
            note["tier_source"] = "数值推断"
        elif "爆" in thresholds and n_interactions >= thresholds["爆"]:
            note["tier"] = "爆"
            note["tier_source"] = "数值推断"

    # ── 观众分析 → actual_audience_data (WTG · 确定性解析, 不用 LLM) ──
    # 飞书「观众分析」列映射成 _audience_raw 时, 解析半结构化文本
    # ("性别分布：男4%女96%；年龄分布：...；阅读时长：12.5秒") 进 JSONB.
    if "_audience_raw" in intermediates:
        # parse_audience_analysis 内部已把 list/dict(富文本多段)归一成【；分段文本】再解析
        # (见 _common._audience_text: 段空串拼接、保住 ；分段, 不像 _direction_key 用逗号连)——
        # 飞书把「观众分析」返回成富文本 list 时也不再静默丢数据(codex PR#59)。
        parsed_audience = parse_audience_analysis(intermediates["_audience_raw"])
        if parsed_audience:
            note["actual_audience_data"] = parsed_audience
            note["audience_actual_synced_at"] = _iso_now()
        consumed_intermediates.add("_audience_raw")

    # ── 伪爆贴标记 (WTG · 「笔记状态」含"关注" = 人工伪造的假数据) ──
    # 这种数据指标做不得真, 但代表运营认为这篇有潜力. 标 data_quality_flags
    # 让下游 (v_autowriter_injection_candidates) 排除, 防假爆款污染飞轮.
    if "_note_status_raw" in intermediates:
        nsr = str(intermediates["_note_status_raw"] or "")
        note.setdefault("raw_extra", {})["_note_status_raw"] = nsr
        flags = dict(note.get("data_quality_flags") or {})
        if "关注" in nsr:
            flags["synthetic"] = True
            flags["synthetic_reason"] = "笔记状态含'关注'=人工伪爆贴; 指标不可信但有潜力信号"
        else:
            # resync 时若状态从"关注"改回正常, 必须显式清除旧 synthetic 标记 ——
            # upsert 只 SET payload 里出现的列, 不写 data_quality_flags 会让 DB
            # 里的旧 true 残留, 行被 v_autowriter_injection_candidates 永久排除
            # (codex PR #19 review). 显式写 false + 去掉 reason.
            flags["synthetic"] = False
            flags.pop("synthetic_reason", None)
        note["data_quality_flags"] = flags
        consumed_intermediates.add("_note_status_raw")

    # Any intermediate that wasn't consumed above (e.g. _account_name,
    # _account_followers, _comment_text, _comment_text_persona) goes to
    # raw_extra so it doesn't get silently dropped.  Future code can
    # process them out of intermediates and write to dedicated tables
    # (e.g. accounts / account_snapshots / comments).
    leftover = {k: v for k, v in intermediates.items() if k not in consumed_intermediates}
    if leftover:
        note.setdefault("raw_extra", {}).update(leftover)

    # ── metric_snapshot from impressions/reads/interactions ──
    # Two-tier split: NOTES_AND_METRIC cols are valid on truth_vault.notes AND
    # also fan out to metric_snapshots. METRIC_ONLY cols (likes/saves/shares/
    # comments_count/search_rank/keyword_rank) don't exist on truth_vault.notes
    # — if they ever sneak into the note payload (because a mapping yaml
    # eventually targets them directly), the notes UPSERT would fail with
    # "column does not exist". Strip them out of `note` before returning so
    # the structural boundary is enforced at the transformer, not by hope.
    metric: dict[str, Any] = {}
    notes_and_metric_cols = ("impressions", "reads", "interactions", "hit_blue_keywords")
    metric_only_cols = ("likes", "saves", "shares", "comments_count",
                        "search_rank", "keyword_rank")
    all_metric_cols = notes_and_metric_cols + metric_only_cols
    if any(c in note for c in all_metric_cols):
        # Compute hours_since_publish + best-fit window_label from publish_time
        # if it's available. Doing this here means even runs that only stamp
        # 'ad_hoc' get a usable bucket label for time-series aggregation later
        # (e.g. group by COALESCE(window_label,'ad_hoc') for a histogram-style
        # view of "interactions at +24h vs +7d"). Note: this is best-effort —
        # the canonical time-series flow requires multiple sync passes per
        # note at the actual windows, which the operator doesn't yet do.
        # 详见 CURRENT_STATE.md 延后清单 § metric_snapshots 时序回收.
        publish_time = note.get("publish_time")
        hours_since_publish, window_label = _derive_metric_window(publish_time)
        metric = {
            "note_id": note["note_id"],
            "collected_at": _iso_now(),
            "window_label": window_label,    # heuristic from hours_since_publish or 'ad_hoc'
            "source": "feishu_import",
            **{c: note[c] for c in all_metric_cols if c in note},
        }
        if hours_since_publish is not None:
            metric["hours_since_publish"] = hours_since_publish
    for c in metric_only_cols:
        note.pop(c, None)

    return note, metric, undeclared


# Mapping of (lower, upper) hours-since-publish bounds → canonical
# window_label per schemas/notes_v1_2.sql CHECK constraint. Bounds are
# inclusive at the lower edge, exclusive at the upper. Any value outside
# all bounds falls back to 'ad_hoc'.
_WINDOW_BOUNDS = (
    (0,    3,   "2h"),       # 0-3h → 2h window
    (3,    36,  "24h"),      # 3-36h → 24h window
    (36,   120, "72h"),      # 36-120h → 72h window
    (120,  240, "7d"),       # 120-240h ≈ 5-10d → 7d window
    (240,  504, "14d"),      # 240-504h ≈ 10-21d → 14d window
    (504,  1080,"30d"),      # 504-1080h ≈ 21-45d → 30d window
    (1080, 365*24, "final"), # 45d-1y → final
)


def _derive_metric_window(publish_time_iso: str | None) -> tuple[int | None, str]:
    """Return (hours_since_publish, window_label) for a metric snapshot.

    publish_time is a naive UTC ISO string (per project convention). When
    it's missing or unparseable, returns (None, 'ad_hoc') — the historical
    backward-compatible behavior. Bucketing is purely heuristic; see
    _WINDOW_BOUNDS for the cutoffs.
    """
    if not publish_time_iso:
        return None, "ad_hoc"
    try:
        from datetime import datetime as _dt
        pt = _dt.fromisoformat(str(publish_time_iso).replace("Z", "+00:00"))
        if pt.tzinfo is not None:
            pt = pt.replace(tzinfo=None)
        delta = _dt.utcnow() - pt
    except (ValueError, TypeError):
        return None, "ad_hoc"
    hrs = int(delta.total_seconds() // 3600)
    if hrs < 0:
        # Future publish_time — operator typo or pre-scheduled note. Don't
        # claim a window, just record the (impossible) hour count so it's
        # visible in queries.
        return hrs, "ad_hoc"
    for lo, hi, label in _WINDOW_BOUNDS:
        if lo <= hrs < hi:
            return hrs, label
    return hrs, "ad_hoc"


_NUMERIC_COLS = {
    "impressions", "reads", "interactions",
    "likes", "saves", "shares", "comments_count",
    "search_rank", "keyword_rank",
}

# Columns whose schema type is TEXT[] — must be parsed as arrays even if
# Feishu returned a comma-separated string (some Bitable columns are plain
# text, not multi-select).  parse_array() handles both shapes uniformly.
# This set should mirror every TEXT[] column in truth_vault.notes so we
# don't ship a string into a TEXT[] column even if a project's mapping
# yaml maps directly there (audit round 5 issue #2).
_ARRAY_COLS = {
    "hit_blue_keywords", "target_blue_keywords",
    "hashtags", "tags",
    "target_audience",
    "human_truth_archetype",
    "trend_dependencies",
}


def _coerce_value(target_col: str, value: Any) -> Any:
    """Cast Feishu cell values to types friendly to Postgres.

    Feishu returns:
      - Text/Number cells: str/int/float/None
      - Multi-select / link cells: list of dicts with 'text' key
      - Date cells: int (milliseconds since epoch)
    We collapse the obvious cases.  Extend per project as needed.

    For numeric columns we apply parse_numeric (handles Chinese commas,
    full-width digits, '/' / '-' / '无' sentinel tokens).  For array
    columns we apply parse_array (handles both list[dict{text}] and
    delimiter-separated text strings).  For publish_time we apply
    parse_feishu_date (accepts ms epoch or ISO string).
    """
    if value is None:
        return None

    # Numeric columns — parse robustly, may return None for sentinel values
    if target_col in _NUMERIC_COLS:
        n = parse_numeric(value)
        if n is None:
            return None
        # If the column is INT-shaped, cast.  Postgres will round/error
        # on non-integer values anyway; cast here for clarity.
        return int(n) if n == int(n) else n

    # Array columns — must be list[str] for TEXT[] target.
    # Handle both list[dict{text:...}] AND "a, b, c" / "a\nb\nc" strings
    # (some Bitable columns are plain text, not multi-select).
    if target_col in _ARRAY_COLS:
        return parse_array(value)

    # Date column — handle 飞书 ms epoch
    if target_col == "publish_time":
        return parse_feishu_date(value)

    # Multi-select / link / attachment cells: list of dicts with 'text'
    # (for non-array target columns we collapse to a comma-separated string)
    if isinstance(value, list):
        if all(isinstance(x, dict) and "text" in x for x in value):
            return ", ".join(x["text"] for x in value)
        return value

    # Single-select / user cell: dict with 'text'
    if isinstance(value, dict) and "text" in value:
        return value["text"]

    return value


# ═════════════════════════════════════════════════════════════════════════
# Upsert into truth_vault
# ═════════════════════════════════════════════════════════════════════════

def upsert_note(client: Client, note: dict[str, Any], dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[dry-run] would upsert note_id=%s", note["note_id"])
        return
    (
        client.schema("truth_vault")
        .table("notes")
        .upsert(note, on_conflict="note_id")
        .execute()
    )


def upsert_metric(client: Client, metric: dict[str, Any], dry_run: bool = False) -> None:
    if not metric:
        return
    if dry_run:
        logger.info(
            "[dry-run] would upsert metric_snapshot note_id=%s window=%s",
            metric["note_id"], metric["window_label"],
        )
        return
    # UNIQUE(note_id, window_label, source) lets us upsert on the composite key
    (
        client.schema("truth_vault")
        .table("metric_snapshots")
        .upsert(metric, on_conflict="note_id,window_label,source")
        .execute()
    )


_BATCH_CHUNK = 500


def ensure_accounts_batch(
    client: Client, account_platforms: dict[str, str], *,
    dry_run: bool = False, chunk_size: int = _BATCH_CHUNK,
) -> None:
    """Batch version of ensure_account_exists: upsert unique accounts in chunks
    instead of one call per note. ignore_duplicates preserves first_seen_at.
    Falls back to per-row (ensure_account_exists) if a chunk fails."""
    if dry_run or not account_platforms:
        return
    rows = [
        {"account_id": aid, "platform": plat, "owner_type": "素人",
         "first_seen_at": _iso_now()}
        for aid, plat in account_platforms.items()
    ]
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        try:
            (
                client.schema("truth_vault").table("accounts")
                .upsert(chunk, on_conflict="account_id", ignore_duplicates=True)
                .execute()
            )
        except Exception as exc:
            logger.warning("accounts batch [%d:%d] failed (%s); per-row fallback",
                           i, i + len(chunk), exc)
            for row in chunk:
                try:
                    ensure_account_exists(client, row["account_id"], platform=row["platform"])
                except Exception:
                    logger.exception("per-row account upsert failed: %s", row.get("account_id"))


def upsert_notes_batch(
    client: Client, notes: list[dict[str, Any]], *,
    dry_run: bool = False, chunk_size: int = _BATCH_CHUNK,
) -> set[str]:
    """Batch-upsert notes (one call per chunk); returns the SET of note_ids
    successfully written. On a chunk failure, falls back to per-row
    (upsert_note) so one bad row can't drop the whole chunk.

    Returning the written ids (not just a count) lets the caller skip metric
    rows whose note failed to land. Otherwise an orphan metric hits the
    metric_snapshots.note_id FK, fails the whole metrics chunk, degrades it to
    a per-row retry, and every orphan re-fails — pure log noise + slowdown."""
    if dry_run:
        for n in notes:
            logger.info("[dry-run] would upsert note_id=%s", n["note_id"])
        return {n["note_id"] for n in notes}
    written: set[str] = set()
    for i in range(0, len(notes), chunk_size):
        chunk = notes[i:i + chunk_size]
        try:
            (
                client.schema("truth_vault").table("notes")
                .upsert(chunk, on_conflict="note_id").execute()
            )
            written.update(n["note_id"] for n in chunk)
        except Exception as exc:
            logger.warning("notes batch [%d:%d] failed (%s); per-row fallback",
                           i, i + len(chunk), exc)
            for n in chunk:
                try:
                    upsert_note(client, n)
                    written.add(n["note_id"])
                except Exception:
                    logger.exception("per-row note upsert failed note_id=%s", n.get("note_id"))
    return written


def upsert_metrics_batch(
    client: Client, metrics: list[dict[str, Any]], *,
    written_note_ids: set[str] | None = None,
    dry_run: bool = False, chunk_size: int = _BATCH_CHUNK,
) -> None:
    """Batch-upsert metric_snapshots; per-row fallback (upsert_metric) on a
    chunk failure.

    If `written_note_ids` is given, drop any metric whose note_id isn't in it —
    that note failed to upsert, so its metric would violate the
    metric_snapshots.note_id FK and sink the whole chunk into a per-row retry."""
    if written_note_ids is not None:
        orphaned = [m for m in metrics if m["note_id"] not in written_note_ids]
        if orphaned:
            logger.warning(
                "skipping %d metric(s) whose note failed to upsert (FK safety): %s",
                len(orphaned), [m["note_id"] for m in orphaned[:10]],
            )
        metrics = [m for m in metrics if m["note_id"] in written_note_ids]
    if dry_run:
        for m in metrics:
            logger.info("[dry-run] would upsert metric_snapshot note_id=%s window=%s",
                        m["note_id"], m["window_label"])
        return
    for i in range(0, len(metrics), chunk_size):
        chunk = metrics[i:i + chunk_size]
        try:
            (
                client.schema("truth_vault").table("metric_snapshots")
                .upsert(chunk, on_conflict="note_id,window_label,source").execute()
            )
        except Exception as exc:
            logger.warning("metrics batch [%d:%d] failed (%s); per-row fallback",
                           i, i + len(chunk), exc)
            for m in chunk:
                try:
                    upsert_metric(client, m)
                except Exception:
                    logger.exception("per-row metric upsert failed note_id=%s", m.get("note_id"))


# ═════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id", help="e.g. NUC_phase1")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without writing to Supabase")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N records (debug)")
    args = parser.parse_args()

    mapping = load_mapping(args.project_id)
    sync_config = mapping.get("sync_config") or {}

    # 夜间 cron 跳过未启用项目(sync_interval=on_demand): 防新接的表(填了坐标但还没 preflight
    # 验证)被 02:00 cron 自动灌(codex PR#67 review)。daily-sync.yml 在 schedule 触发时置
    # TV_SCHEDULED_RUN=true; 显式 Run workflow / 本地手跑不置 → 照常跑。验证 OK 后把
    # sync_interval 改 daily 即进夜间 cron。
    scheduled = os.environ.get("TV_SCHEDULED_RUN") == "true"
    if _skip_on_demand_on_cron(sync_config.get("sync_interval"), scheduled):
        logger.info(
            "project %s: sync_interval=on_demand → 夜间 cron 跳过(未启用)。显式 Run workflow"
            "(填 project)可手动跑; preflight 验证 OK 后把 sync_interval 改成 daily 入夜间 cron。",
            args.project_id,
        )
        return 0

    # source_type discriminator: this script only handles feishu_api.
    # manual_xlsx ingest is not in scope — would require a different
    # ingest path (read .xlsx → coerce → upsert).  Fail fast and loud
    # so the operator doesn't run this script against a manual project.
    source_type = sync_config.get("source_type", "feishu_api")
    if source_type != "feishu_api":
        logger.error(
            "Mapping yaml has sync_config.source_type=%r. This script only "
            "handles 'feishu_api'.  For 'manual_xlsx' projects you need a "
            "separate ingest path (not included in this package).",
            source_type,
        )
        return 2

    app_token = sync_config.get("feishu_app_token") or os.environ.get("FEISHU_APP_TOKEN")
    table_id  = sync_config.get("feishu_table_id")  or os.environ.get("FEISHU_TABLE_ID")
    view_id   = sync_config.get("feishu_view_id")
    if not app_token and not table_id:
        # 两个定位符【都】空 = 占位、该项目【还没 onboard】→ 优雅跳过(非错误, exit 0)。
        # 否则 daily-sync 跑全量时, 任何尚未 onboard 的占位项目都会拖垮整个 cron
        # (2026-06-02 实测: NUC/NRT 占位 → cron 全红)。接入: 在 mappings/<project>.yaml
        # 的 sync_config 同时填 feishu_app_token + feishu_table_id。
        logger.warning(
            "project %s 未配 feishu sync_config (app_token + table_id 都为空) "
            "→ 尚未 onboard, 跳过(非错误)。接入请在 mappings/%s.yaml 填 sync_config。",
            args.project_id, args.project_id,
        )
        return 0
    if not app_token or not table_id:
        # 只配了【一半】= 配置写错(漏填/拼错), 不是"未 onboard" → 仍报错暴露, 别假装
        # 成功却一行都不同步 (PR#32 review r3339895103)。
        logger.error(
            "project %s 的 feishu sync_config 只配了一半 "
            "(feishu_app_token 有=%s / feishu_table_id 有=%s) — 这是配置错误、不是未 onboard。"
            "请检查 mappings/%s.yaml 的 sync_config 是否漏填或拼错。",
            args.project_id, bool(app_token), bool(table_id), args.project_id,
        )
        return 2

    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        logger.error("FEISHU_APP_ID and FEISHU_APP_SECRET env vars must be set.")
        return 2

    fs = FeishuClient(app_id, app_secret)
    sb = get_supabase_client()

    # Make sure truth_vault.projects has the row before any notes go in —
    # `notes.project_id` has a FK to it and would reject every insert
    # without this (audit issue 2 from session #8 round 4).
    if not args.dry_run:
        ensure_project_exists(sb, mapping)

    stats = {"total": 0, "upserted": 0, "quarantined": 0,
             "empty_placeholder": 0, "errors": 0}
    # Collect transformed rows, then write in batches after the loop (one
    # upsert per chunk instead of ~3 REST calls per record — see *_batch above).
    pending_notes: list[dict[str, Any]] = []
    pending_metrics: list[dict[str, Any]] = []
    account_platforms: dict[str, str] = {}
    for item in fs.list_records(app_token, table_id, view_id):
        if args.limit and stats["total"] >= args.limit:
            break
        stats["total"] += 1
        feishu_record_id = item.get("record_id", "")
        raw_fields = item.get("fields", {})
        try:
            note, metric, undeclared = transform_row(mapping, feishu_record_id, raw_fields)
            if undeclared:
                logger.warning(
                    "record_id=%s has undeclared fields: %s → quarantine",
                    feishu_record_id, undeclared,
                )
                if not args.dry_run:
                    quarantine_record(
                        sb, mapping["project_id"], feishu_record_id,
                        raw_fields, undeclared, reason="undeclared_fields",
                    )
                stats["quarantined"] += 1
                continue  # Don't upsert; require human review first

            # Required-field check: truth_vault.notes has NOT NULL constraints
            # on raw_content (the actual note text), and INSERT would crash
            # mid-batch if a row from Feishu is blank or malformed.  Quarantine
            # instead so the operator sees the problematic row alongside the
            # undeclared-fields cases, rather than the whole sync failing.
            REQUIRED_NOTE_FIELDS = ("raw_content",)
            missing = [c for c in REQUIRED_NOTE_FIELDS if not note.get(c)]
            if missing:
                # 空占位/碎片行(只缺 raw_content 且无任何 note-like 实质信号)= 父记录占位 / 评论碎片,
                # 大量且每轮重复 → 静默计数, 收尾出一行汇总, 不逐条刷 WARNING。
                # 有 note-like 信号却缺 raw_content 的异常行 → 仍逐条 WARNING(本该是笔记却丢正文, 值得查)。
                is_empty_placeholder = missing == ["raw_content"] and not any(
                    note.get(k) for k in _NOTE_DATA_SIGNALS
                )
                if is_empty_placeholder:
                    stats["empty_placeholder"] += 1
                else:
                    logger.warning(
                        "record_id=%s missing required fields: %s → quarantine",
                        feishu_record_id, missing,
                    )
                if not args.dry_run:
                    quarantine_record(
                        sb, mapping["project_id"], feishu_record_id,
                        raw_fields, missing,
                        reason=f"missing_required:{','.join(missing)}",
                    )
                stats["quarantined"] += 1
                continue

            # Collect for the batched write after the loop. Dedupe the account
            # here (notes.account_id FK → accounts) so each account upserts once.
            acct = note.get("account_id")
            if acct:
                account_platforms.setdefault(acct, note.get("platform", "xiaohongshu"))
            pending_notes.append(note)
            if metric:
                pending_metrics.append(metric)
        except Exception as exc:
            logger.exception("record_id=%s failed: %s", feishu_record_id, exc)
            stats["errors"] += 1

    # ── Batch write (FK order: project → accounts → notes → metrics) ──
    ensure_accounts_batch(sb, account_platforms, dry_run=args.dry_run)
    written_ids = upsert_notes_batch(sb, pending_notes, dry_run=args.dry_run)
    # Only write metrics for notes that actually landed — a metric whose note
    # failed to upsert would violate the metric_snapshots.note_id FK (see
    # upsert_metrics_batch). In dry-run written_ids holds all ids, so nothing
    # is filtered.
    upsert_metrics_batch(sb, pending_metrics, written_note_ids=written_ids,
                         dry_run=args.dry_run)
    stats["upserted"] = len(written_ids)
    stats["errors"] += len(pending_notes) - len(written_ids)

    # Roll up project-level date range from the freshly synced notes. The yaml
    # placeholders (auto_from_publish_time_min/max) aren't DATE-castable, so
    # this is the only path that keeps projects.start_date/end_date honest.
    if not args.dry_run:
        try:
            update_project_date_range(sb, mapping["project_id"])
        except Exception as exc:
            logger.warning("update_project_date_range failed for %s: %s",
                           mapping["project_id"], exc)

    if stats["empty_placeholder"]:
        logger.info(
            "跳过 %d 行空占位/评论碎片行(无正文、无账号/指标/链接等实质信号; 已 quarantine 留档, 未逐条告警)",
            stats["empty_placeholder"],
        )
    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
