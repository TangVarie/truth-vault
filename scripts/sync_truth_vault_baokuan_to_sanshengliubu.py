"""
sync_truth_vault_baokuan_to_sanshengliubu.py
═══════════════════════════════════════════════════════════════════════════

把 Truth Vault 中 tier ∈ ('爆', '大爆', '参考') 的笔记 sync 到
public.reference_samples（sanshengliubu 保持在 public schema，D-024）。
注入到 vibe_rewriter 的高权重检索池。

用法:
    python sync_truth_vault_baokuan_to_sanshengliubu.py
    python sync_truth_vault_baokuan_to_sanshengliubu.py --project NUC_phase1
    python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run

⚠️ 默认【不推】sync_interval=on_demand 的项目 —— 没翻 daily = 还没拍板, 而这一步是
   跨库单向的(写进三生六部的生产检索池, 推过去追不回来)。要单推走 --include-on-demand;
   `--project X` 不自带这个豁免。详见 drop_on_demand_projects() 的 docstring。

幂等性:
    主键: public.reference_samples.source_truth_vault_note_id（专门加的
          干净索引列，由 sanshengliubu-patches/001_add_source_tv_note_id.sql
          创建）。这是判断「已 sync」的正式幂等键，preflight_check 会拒绝
          没有该列的部署。
    Fallback: 仅对历史行（migration 之前 insert 的 row）会回退到
          ai_analysis->>'_truth_vault_note_id'。新写入一律两个都填，未来
          可以把 fallback 路径删掉。
    重跑只会处理新出现的爆款。

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY       (必须用 service_role，绕过 RLS)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

from _common import (
    fetch_all_pages,
    get_supabase_client,
    load_mapping,
    setup_logger,
    skip_on_demand_on_cron,
    _iso_now,
)


logger = setup_logger("sync_tv_baokuan_to_ssll")


# TV canonical platform key (English, see schemas/notes_v1_2.sql) → sanshengliubu
# UI display name (Chinese, see sanshengliubu pipeline/config.py:DEFAULT_PLATFORM and
# pages/2_new_project.py 平台选项). sanshengliubu 的 list_reference_packs 用
# `.eq("platform", platform)` 精确过滤，其中 platform 来自项目配置（中文）。
# 不翻译就会导致 TV 写入 'xiaohongshu' 而 sanshengliubu 检索 '小红书' 永远空。
_PLATFORM_EN_TO_SSLL: dict[str, str] = {
    "xiaohongshu": "小红书",
    "douyin":      "抖音",
    "weibo":       "微博",
    "bilibili":    "B站",
    "kuaishou":    "快手",
}

# 2026-05-22 audit P2: 老版本不在 dict 里的平台会 silent fallback 写英文,
# sanshengliubu 用中文检索时永远空, 飞轮静默漂移. 改成显式白名单 (中+英)
# + 未知平台立刻报错. 加新平台必须先在两边都加, 防漏。
_PLATFORM_ALLOWED_ZH: frozenset[str] = frozenset(_PLATFORM_EN_TO_SSLL.values())


def _platform_for_ssll(en_or_zh: str | None) -> str:
    """Map TV's canonical English platform key to sanshengliubu's display name.

    - None / 空 → 默认 "小红书" (TV 单一品类目前都跑小红书)
    - 已知 英文 (xiaohongshu / douyin / ...) → 翻译成对应中文
    - 已知 中文 (小红书 / 抖音 / ...) → 直接放过
    - 其他 → ValueError. 不再 silent fallback, 防"看似在跑实际飞轮断"。

    新增平台时:
      1. 这里 _PLATFORM_EN_TO_SSLL 加一行
      2. sanshengliubu 仓那边确认新平台在 list_reference_packs 检索逻辑里有处理
      3. truth-vault docs/03-mapping-protocol.md platform 枚举更新
    """
    if not en_or_zh:
        return "小红书"
    if en_or_zh in _PLATFORM_EN_TO_SSLL:
        return _PLATFORM_EN_TO_SSLL[en_or_zh]
    if en_or_zh in _PLATFORM_ALLOWED_ZH:
        return en_or_zh
    raise ValueError(
        f"Unknown platform {en_or_zh!r}. Add it to _PLATFORM_EN_TO_SSLL "
        "in this file AND confirm sanshengliubu list_reference_packs handles it. "
        f"Currently allowed: en={sorted(_PLATFORM_EN_TO_SSLL.keys())}, "
        f"zh={sorted(_PLATFORM_ALLOWED_ZH)}"
    )


def fetch_pending_baokuan(
    sb,
    project_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query Truth Vault for baokuan notes not yet synced to sanshengliubu.

    Eligibility filters (matching通道 2 D-036 data-hygiene rules):
      - tier ∈ ('爆','大爆','参考')                       爆款 + 运营标的参考级 (参考权重低)
      - tier_source != '数值推断'                          排除未人工 confirm 的自动 tier
                                                          (运营要把某条数值推断的 row
                                                          重新纳入 sync, 改 tier_source 为
                                                          '人工补录': UPDATE notes SET
                                                          tier_source='人工补录' WHERE
                                                          note_id=...) ⚠️但只改 DB
                                                          当前行、不持久: 下次该项目飞书回灌
                                                          会按源头重算覆盖 tier_source.
                                                          持久做法见 docs/13 路径 A
                                                          (飞书源头标 tier))
      - publish_time within 12 months                     不持续推过气审美进 ssll
                                                          的 reference_samples
      - synced_to_ssll_at IS NULL                         未同步
      - data_quality_flags.synthetic (分级处理)              排除伪爆贴 (WTG「笔记状态」
                                                          含"关注"的人工假数据). 和通道 2
                                                          v_autowriter_injection_candidates
                                                          的 synthetic 排除"曾"全量对齐; 2026-06-01 起通道1细化为只挡
                                                          指标撑的 爆/大爆; 参考 放行 (纯人工判断·与指标真假无关). 详见下方 fetch 过滤注释.

    Paginates explicitly. Supabase's PostgREST defaults to 1000 rows/response;
    once enough projects onboard, unsynced 爆款 will cross that boundary and
    silent truncation would leak baokuan from the flywheel.
    """
    from datetime import datetime, timedelta, timezone
    twelve_months_ago = (
        datetime.now(timezone.utc) - timedelta(days=365)
    ).replace(tzinfo=None).isoformat(timespec="seconds")

    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, raw_content, hit_blue_keywords, "
                "tier, tier_source, intent, publish_url, publish_time, "
                "target_audience, data_quality_flags, projects(category, brand, platform)")
        .in_("tier", ["爆", "大爆", "参考"])
        .neq("tier_source", "数值推断")
        .gte("publish_time", twelve_months_ago)
        .is_("synced_to_ssll_at", None)
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    rows = fetch_all_pages(q, order_by="note_id")
    # 伪爆贴 (synthetic = 人工刷的假指标, 如 WTG「笔记状态」含"关注") 分级处理
    # (2026-06-01 运营决定):
    #   - 指标型 tier (爆/大爆): 排除. 它们的"爆"是假数据撑的, 不可信.
    #   - 参考: 放行. "参考"是运营纯人工判断("这条内容值得参考"), 与指标真假无关;
    #     synthetic_reason 本身就写"指标不可信但有潜力信号", 标参考正是认领这潜力.
    #     参考本就低权重 (quality_score=0), 且 reference_samples 喂的是内容不是指标,
    #     假数据不外泄. 通道 2 只取爆/大爆, 不受此影响.
    # 仍在 Python 过滤而非 PostgREST: JSONB ->>'synthetic' 为 NULL (绝大多数正常行)
    # 时 neq.true 会把 NULL 也滤掉 (NULL<>'true'=NULL=不通过), Python 端显式判最稳.
    def _is_synthetic(r: dict[str, Any]) -> bool:
        f = r.get("data_quality_flags")
        return isinstance(f, dict) and f.get("synthetic") is True

    return [
        r for r in rows
        if not (_is_synthetic(r) and r.get("tier") in ("爆", "大爆"))
    ]


def drop_on_demand_projects(
    pending: list[dict[str, Any]],
    include_on_demand: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """把 sync_interval=on_demand 项目的爆款从待推列表里摘掉。

    D-047 的第三张嘴, 也是【唯一跨库】的那张: 入库 / essence / curate 都在 truth_vault
    自己家里, 而这一步把内容写进另一个 Supabase 的 public.reference_samples ——
    三生六部检索池, 直接喂写作引擎。一旦推过去, TV 这边再改 mapping 也追不回来
    (只有 synthetic 那条自愈路径能回收, 见 retract_stale_synthetic_from_ssll)。

    为什么之前漏了: 这一步在 daily-sync.yml 里【根本没有项目循环】—— 一句
    `python sync_truth_vault_baokuan_to_sanshengliubu.py` 全局跑, 而 fetch_pending_baokuan
    只按 tier/publish_time/synced_to_ssll_at 取, 不看 sync_interval。所以一张没验证过的
    表笔记落库的当晚, 它的爆款就进了写作引擎的参考池 —— 带着还是 [待确认] 的
    target_audience / 方向拆解一起过去(build_reference_sample 会把这些字段写进样本)。

    ⚠️ 这一道与 essence / curate 那两道【故意不同】: 那两道只挡夜间 cron、不挡人工
    (`skip_on_demand_on_cron(si, scheduled)` 的第二个参数是真实的 scheduled),
    本道对【任何一次跑】都挡, 不看是不是 cron。因为风险类别不同:

        essence / curate : 写在 truth_vault 自己家里, 幂等, 改完 mapping 能重跑。
        通道1(本步)      : 一次性写进另一个团队的生产检索池, 没有回头路。

    "手动触发"并不会让 mapping 里那些 [待确认] 变成已拍板。接表 SOP 的顺序是
    preflight → 显式跑一次验证 → 拍板 → 翻 daily; 中间那次【验证性质的实跑】
    如果顺手把结果推进另一个团队的生产检索池, 那不叫验证。

    要单推某个还没翻 daily 的项目, 走 `--include-on-demand`(指名道姓的那条路);
    永久的那条是把它翻成 daily —— 与 LNKT yaml 里
    "翻 daily 时要同步提醒 ssll 那边对齐平台名写法" 说的是同一个时刻。
    注意 `--project X` 【不】自带这个豁免: 一个开关一个意思, 免得"我只是想定向跑一下"
    顺手变成"我同意把它推进写作引擎"。

    判据仍走 _common.skip_on_demand_on_cron —— 与入库/essence/curate 同一份, 不重写,
    只是第二个参数恒为 True(本步把每一次跑都当 cron 对待, 见上)。
    判不了(项目没有 mapping 文件 / yaml 读不出来)→ 【照推】, 与 skip_on_cron.py 的
    exit 2 同取向: 静默少推查起来毫无线索, 多推最多是下游多一条本来就要人审的样本。

    回收(retract_stale_synthetic_from_ssll)【不】受这道闸管 —— 它是把已经推错的东西
    拉回来, 任何时候都该跑; 闸挡的是"往外推", 不是"往回收"。

    返回 (要推的行, {被跳过的 project_id: 行数})。
    """
    if include_on_demand:
        return pending, {}
    cache: dict[str, bool] = {}          # project_id → 该跳过吗(每个项目只读一次 yaml)

    def _should_skip(project_id: str) -> bool:
        if project_id not in cache:
            try:
                sync_interval = (
                    (load_mapping(project_id).get("sync_config") or {}).get("sync_interval")
                )
            except Exception as exc:      # noqa: BLE001 —— 判不了就照推
                logger.warning(
                    "读不出 %s 的 mapping(%s) → 判不了, 按【照推】处理", project_id, exc
                )
                sync_interval = None
            cache[project_id] = skip_on_demand_on_cron(sync_interval, True)
        return cache[project_id]

    kept: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for note in pending:
        pid = note.get("project_id") or ""
        if _should_skip(pid):
            skipped[pid] = skipped.get(pid, 0) + 1
        else:
            kept.append(note)
    return kept, skipped


def retract_stale_synthetic_from_ssll(
    sb,
    project_filter: str | None = None,
    dry_run: bool = False,
) -> int:
    """自愈回收:把【现在是 synthetic 爆/大爆】却仍有 ssll 样本/同步标记的, 从 ssll 撤回。

    为什么需要:synthetic 标记可能在【同步之后】才打上 —— 运营事后在飞书把「笔记状态」标
    「关注」(WTG 式), 或在【流量状态】写「伪爆贴」(RIO 式), 而该帖此前已作为"真爆款"同步进 ssll。
    push 侧 `fetch_pending_baokuan` 的 synthetic 过滤只挡【新】同步, 不回收旧的 —— 旧的会以
    高权重停留在 ssll `reference_samples`, 污染 vibe 仿写。本函数与 push 过滤【对称】
    (`synthetic AND tier∈(爆,大爆)` 才撤;参考放行、不动), 每次 sync 跑一遍即自愈。

    候选 = synthetic 爆/大爆【全部】(不只看 synced_to_ssll_at)—— 因为存在 orphan 行:
    insert_reference_sample 成功但 mark_synced 失败时, ssll 有样本而 TV 侧 synced_to_ssll_at
    仍为 NULL(见 existing_ssll_sample_id docstring);只看 synced 标记会漏掉它们(codex PR#98 review)。
    对每条用 existing_ssll_sample_id 走【顶层列 + ai_analysis fallback 键】双路查到样本 id 再按 id 删
    —— 覆盖回填 source_truth_vault_note_id 之前同步的 legacy 行(同 review)。最后清 synced_to_ssll_at。
    """
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, tier, synced_to_ssll_at, data_quality_flags")
        .in_("tier", ["爆", "大爆"])
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    # synthetic 判定在 Python 端(JSONB ->>'synthetic' 的 PostgREST 过滤对 NULL 行不稳, 同
    # fetch_pending_baokuan)。不再用 synced_to_ssll_at 预筛 —— orphan 行该标记为 NULL 也要回收。
    candidates = [
        r for r in fetch_all_pages(q, order_by="note_id")
        if isinstance(r.get("data_quality_flags"), dict)
        and r["data_quality_flags"].get("synthetic") is True
    ]
    retracted = 0
    for r in candidates:
        note_id = r["note_id"]
        # 双键查 ssll 样本(顶层 source_truth_vault_note_id + 旧行的 ai_analysis->>_truth_vault_note_id)。
        sample_id = existing_ssll_sample_id(sb, note_id)
        if sample_id is None and not r.get("synced_to_ssll_at"):
            continue  # ssll 无样本、TV 也没标 synced → 本就不在飞轮, 无需动作
        if dry_run:
            logger.info("[dry-run] would retract stale-synthetic baokuan from ssll: %s (sample=%s)",
                        note_id, sample_id)
            retracted += 1
            continue
        if sample_id is not None:
            # 按 id 删(双键已解析到具体行)—— 不碰 ssll 原生样本(它们无 TV lineage 键)。
            sb.schema("public").table("reference_samples").delete().eq("id", sample_id).execute()
        sb.schema("truth_vault").table("notes").update(
            {"synced_to_ssll_at": None, "synced_ssll_reference_sample_id": None}
        ).eq("note_id", note_id).execute()
        logger.warning("Retracted stale-synthetic baokuan from ssll (伪爆贴不污染飞轮): %s (sample=%s)",
                       note_id, sample_id)
        retracted += 1
    return retracted


def fetch_top_comments(sb, note_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Pull top N comments to embed as evidence in the reference pack.

    The truth_vault.comments schema does NOT have likes/sentiment columns
    (those were in an older draft; current schema in schemas/notes_v1_2.sql
    only stores content + comment_role + comment_type + is_pinned +
    contains_blue_keyword + blue_keywords_matched).  We order by pinned
    status first (pinned comments are usually high-signal), then by
    comment_order as a stable tie-breaker.

    Returns dicts with 'content' (not 'text'), 'comment_role', 'is_pinned'.
    """
    res = (
        sb.schema("truth_vault")
        .table("comments")
        .select("content, comment_role, is_pinned, contains_blue_keyword, "
                "blue_keywords_matched, comment_order")
        .eq("note_id", note_id)
        .order("is_pinned", desc=True)
        .order("comment_order", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


def build_reference_sample(note: dict, comments: list[dict]) -> dict:
    """Map a Truth Vault note into a sanshengliubu.reference_samples row.

    Schema source of truth: sanshengliubu's db/schema.sql + db/migrations/
    005_reference_samples_v2.sql. The live v2 columns vibe_rewriter actually
    reads (see pipeline/retrieve_samples._shape_for_rewriter) are:

        id, platform, category, post_title, post_body, top_comments,
        ai_analysis

    Plus the canonical write path (db/supabase_client.save_reference_pack)
    also writes title, source_type, content_text (legacy mirror), tags,
    quality_score.

    Anything NOT in that schema (brand, source_url, target_audience,
    hit_keywords — fields TV cares about but ssll doesn't have columns
    for) goes into ai_analysis under leading-underscore TV-injected keys.

    top_comments shape: live ssll schema is JSONB array of {text, likes?}
    dicts (vibe_rewriter passes the list verbatim to the prompt; extra
    keys are tolerated). truth_vault.comments has no `likes` column, so
    we emit {text, role, pinned} — `role` and `pinned` are extra
    metadata that the prompt may or may not use but don't hurt.
    """
    proj = note.get("projects") or {}
    tier = note.get("tier")
    # tier → quality_score is sanshengliubu's own column (INTEGER) used
    # for "优质优先" sample retrieval ordering.  爆=100, 大爆=200 puts
    # TV-injected samples comfortably above any default 0.
    quality_score = {"爆": 100, "大爆": 200}.get(tier, 0)

    # Comments as [{text, role, pinned}, …] — the shape vibe_rewriter
    # expects (see pipeline/agents/reference_pack_analyzer docstring:
    # `top_comments: [{"text": "...", "likes": 123}, ...]`). `likes`
    # isn't tracked in truth_vault.comments; we omit it rather than
    # invent a fake number.
    top_comments = [
        {
            "text": c.get("content"),
            "role": c.get("comment_role"),
            "pinned": bool(c.get("is_pinned")),
        }
        for c in comments
        if c.get("content")
    ]

    ai_analysis = {
        # Cross-system lineage (leading underscore = TV-injected, not ssll-native).
        "_truth_vault_note_id": note["note_id"],           # idempotency key (also top-level column)
        "_truth_vault_project_id": note["project_id"],
        "_truth_vault_tier": tier,
        "_truth_vault_intent": note.get("intent"),
        "_truth_vault_quality_score": quality_score,
        # TV-specific metadata that ssll's reference_samples schema has no
        # top-level home for. Stash here so any TV-side downstream (e.g.
        # an Analytics view that joins by sample_id) can still see them.
        "_truth_vault_brand": proj.get("brand"),
        "_truth_vault_source_url": note.get("publish_url"),
        "_truth_vault_target_audience": note.get("target_audience"),
        "_truth_vault_hit_blue_keywords": note.get("hit_blue_keywords") or [],
        # synthetic=true 但能到这里 = 运营标了"参考"(内容潜力背书), 其互动指标却是
        # 人工刷的、不可信. 标出来让下游别把这条的"数据"当真. (爆/大爆 的 synthetic
        # 已在 fetch_pending_baokuan 端拦掉, 能到这里的 synthetic 只会是 参考.)
        "_truth_vault_synthetic": bool(
            isinstance(note.get("data_quality_flags"), dict)
            and note["data_quality_flags"].get("synthetic") is True
        ),
    }

    raw_content = note.get("raw_content") or ""
    # Use the first line / first 80 chars as a synthetic title — TV notes
    # don't carry an original post title, so this is the best approximation.
    # 80 chars is what ssll's own save_reference_pack uses.
    synthetic_title = raw_content.split("\n", 1)[0][:80] or "未命名样本"

    return {
        "id": str(uuid.uuid4()),
        # ── Top-level columns ssll's vibe_rewriter actually reads ──
        "post_title": synthetic_title,
        "post_body":  raw_content,
        "top_comments": top_comments,
        # platform: write sanshengliubu's display value (中文) so its
        # list_reference_packs filter `.eq("platform", "小红书")` finds us.
        "platform":   _platform_for_ssll(proj.get("platform") or note.get("platform")),
        "category":   proj.get("category"),
        "ai_analysis": ai_analysis,
        # ── Other top-level columns the canonical write path sets ──
        "title":        synthetic_title,
        # source_type: sanshengliubu list_reference_packs filters
        # `.eq("source_type", "pack")` — writing 'pack' is required for
        # TV samples to appear in vibe_rewriter retrieval. The TV-origin
        # discriminator stays in `tags` below and in `source_truth_vault_note_id`.
        "source_type":  "pack",
        "content_text": raw_content,          # legacy mirror; pre-v2 readers still see it
        "tags": ["truth_vault_sync"] + ([tier] if tier else []),
        "quality_score": quality_score,
        # ── Lineage / idempotency key (added by
        #    sanshengliubu-patches/001_add_source_tv_note_id.sql) ──
        # Without 001, idx_reference_samples_tv_note stays empty and
        # existing_ssll_sample_id() falls back to the slower JSON path.
        "source_truth_vault_note_id": note["note_id"],
        "created_at": _iso_now(),
    }


def preflight_check(sb) -> None:
    """Fail fast if public.reference_samples is missing required columns.

    Runs once at startup. Issues a no-data SELECT with a tight column list;
    Supabase/PostgREST returns 400 with 'column X does not exist' if any
    column is absent. Catching this here (with a curated error message)
    is friendlier than letting the first INSERT explode mid-loop and
    leaving half the run un-synced.

    Required columns are the v2 reference_samples columns
    (db/migrations/005_reference_samples_v2.sql) plus the TV-injected
    lineage key (sanshengliubu-patches/001_add_source_tv_note_id.sql).
    If sanshengliubu renames any of these, update this list,
    build_reference_sample(), and docs/09-system-integration.md in one
    commit.
    """
    required = (
        "id, title, source_type, content_text, post_title, post_body, "
        "top_comments, platform, category, ai_analysis, quality_score, "
        "tags, source_truth_vault_note_id, created_at"
    )
    try:
        sb.schema("public").table("reference_samples").select(required).limit(0).execute()
    except Exception as exc:
        msg = str(exc)
        raise RuntimeError(
            "public.reference_samples preflight failed. The live sanshengliubu "
            "schema is missing one of the columns this script writes. Confirm "
            "sanshengliubu-patches/001_add_source_tv_note_id.sql has been run, "
            "and that sanshengliubu's own db/migrations/005_reference_samples_v2.sql "
            "(the v2 'evidence pack' columns: post_title / post_body / "
            "top_comments / platform / category / ai_analysis / quality_score) "
            f"has also been applied. Underlying error: {msg}"
        ) from exc


def existing_ssll_sample_id(sb, note_id: str) -> str | None:
    """Return the public.reference_samples.id already linked to this TV note,
    or None if no such sample exists.

    Why this exists (audit issue · sub-3):
        The main path uses notes.synced_to_ssll_at IS NULL to find work.
        But there's a race: insert_reference_sample succeeded, then
        mark_synced (UPDATE truth_vault.notes) failed for any reason
        (network blip, process killed, RLS hiccup).  On next run, the
        note is still "pending" so we'd insert a SECOND reference_sample.

        This function is the belt-and-suspenders check: before inserting,
        query reference_samples for the canonical key
        (source_truth_vault_note_id, also kept in ai_analysis for legacy
        rows).  If we find a row, we skip insert and only run mark_synced.

    Two separate queries instead of an OR clause: PostgREST's `or=` is a
    comma-separated string filter, so embedding the raw note_id (which is
    f"{project_id}_{feishu_record_id}") meant a comma or '.' in the value
    could break the parser. Two `.eq()` queries are safer and the cost
    (a second round trip on the rare fallback) is negligible — the index
    on source_truth_vault_note_id makes the first probe ~free, and the
    second probe (the JSON path) runs only when the new column is empty.
    """
    primary = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .eq("source_truth_vault_note_id", note_id)
        .limit(1)
        .execute()
    )
    if primary.data:
        return primary.data[0]["id"]

    fallback = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .eq("ai_analysis->>_truth_vault_note_id", note_id)
        .limit(1)
        .execute()
    )
    if fallback.data:
        return fallback.data[0]["id"]
    return None


def _is_duplicate_error(exc: Exception) -> bool:
    """Detect Postgres unique-constraint violations from supabase-py.

    Same heuristic as the AutoWriter sync script: checks SQLSTATE 23505 in
    multiple possible attribute locations because supabase-py wraps the
    PostgREST error inconsistently across versions.
    """
    code = getattr(exc, "code", None) or getattr(exc, "pgcode", None)
    if code == "23505":
        return True
    msg = str(exc)
    return "23505" in msg or "duplicate key value violates" in msg


def insert_reference_sample(sb, sample: dict, dry_run: bool = False) -> str:
    """Insert a reference_samples row, recovering from concurrent dupes.

    2026-05-22 audit P1-3 update: the existing_ssll_sample_id() check runs
    before this in main(), but it's a separate query — a concurrent worker
    could insert the same source_truth_vault_note_id between our SELECT and
    INSERT. With the new partial UNIQUE index
    (sanshengliubu-patches/003), that race now surfaces as 23505 instead
    of silent duplicate rows. We catch it here and recover by looking up
    the winning row's id, so the caller's mark_synced() still gets a real
    sample_id to write back to truth_vault.notes.
    """
    note_id = sample.get("source_truth_vault_note_id")
    if dry_run:
        logger.info("[dry-run] would insert reference_sample id=%s for note %s",
                    sample["id"], note_id or "(no note id)")
        return sample["id"]
    try:
        (
            sb.schema("public")
            .table("reference_samples")
            .insert(sample)
            .execute()
        )
        return sample["id"]
    except Exception as exc:
        if not _is_duplicate_error(exc):
            raise
        # Race recovery: another worker won. Look up its id by the canonical
        # idempotency key so we still return a real UUID to the caller.
        if not note_id:
            # The dup wasn't on our key but on something else (e.g., primary
            # key collision from a re-used uuid). Re-raise so we don't claim
            # success for a row we didn't write.
            raise
        existing = (
            sb.schema("public")
            .table("reference_samples")
            .select("id")
            .eq("source_truth_vault_note_id", note_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            # 23505 said dup but the lookup found nothing — schema drift or
            # the row was deleted between INSERT and SELECT. Re-raise.
            raise
        winner_id = existing.data[0]["id"]
        logger.info(
            "race recovery: concurrent run inserted reference_sample %s for "
            "note %s first; treating as success", winner_id, note_id,
        )
        return winner_id


def mark_synced(sb, note_id: str, sample_id: str, dry_run: bool = False) -> None:
    """Update truth_vault.notes with sync state for backward traceability."""
    if dry_run:
        logger.info("[dry-run] would mark note %s synced to ssll sample %s",
                    note_id, sample_id)
        return
    (
        sb.schema("truth_vault")
        .table("notes")
        .update({
            "synced_to_ssll_at": _iso_now(),
            "synced_ssll_reference_sample_id": sample_id,
        })
        .eq("note_id", note_id)
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", help="Only sync this project (e.g. NUC_phase1)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N notes (debug)")
    parser.add_argument(
        "--include-on-demand", action="store_true",
        help="连 sync_interval=on_demand 的项目也推(默认不推 —— 没翻 daily = 还没拍板, "
             "而推进三生六部检索池是【没有回头路】的一步; 见 drop_on_demand_projects)",
    )
    args = parser.parse_args()

    sb = get_supabase_client()
    if not args.dry_run:
        preflight_check(sb)
    # 先自愈回收【已同步但现在是 synthetic 爆/大爆】的(伪爆贴最高优先级, 不污染飞轮);再推新爆款。
    retracted = retract_stale_synthetic_from_ssll(sb, project_filter=args.project, dry_run=args.dry_run)
    pending = fetch_pending_baokuan(sb, project_filter=args.project)
    logger.info("Found %d baokuan pending sync to sanshengliubu", len(pending))
    # on_demand 闸 (D-047 第三张嘴, 唯一跨库的一张)。放在 fetch 之后而不是塞进查询里:
    # 判据是 mapping 文件里的 sync_interval, 不是库里的列, PostgREST 查不了。
    pending, gated = drop_on_demand_projects(pending, args.include_on_demand)
    if gated:
        # 明说跳了谁跳了多少 —— 静默过滤会让日志看着像"这些项目本来就没爆款"。
        logger.info(
            "on_demand 闸拦下 %d 条不推三生六部: %s;"
            " 该项目翻 daily(或本次加 --include-on-demand)后照推",
            sum(gated.values()),
            json.dumps(gated, ensure_ascii=False, sort_keys=True),
        )

    stats = {"synced": 0, "recovered": 0, "retracted": retracted, "errors": 0}
    for i, note in enumerate(pending):
        if args.limit and i >= args.limit:
            break
        try:
            # Belt-and-suspenders: ref_samples may already have a row for
            # this TV note (previous run inserted then crashed before
            # mark_synced ran).  In that case skip insert, just write the
            # synced state back.  See existing_ssll_sample_id() docstring.
            existing_id = existing_ssll_sample_id(sb, note["note_id"])
            if existing_id is not None:
                mark_synced(sb, note["note_id"], existing_id, dry_run=args.dry_run)
                stats["recovered"] += 1
                logger.info(
                    "Recovered orphan: ssll sample %s already existed for "
                    "TV note %s; only marking synced",
                    existing_id, note["note_id"],
                )
                continue

            comments = fetch_top_comments(sb, note["note_id"], limit=5)
            sample = build_reference_sample(note, comments)
            sample_id = insert_reference_sample(sb, sample, dry_run=args.dry_run)
            mark_synced(sb, note["note_id"], sample_id, dry_run=args.dry_run)
            stats["synced"] += 1
            logger.info("Synced %s (tier=%s, project=%s) → ssll %s",
                        note["note_id"], note["tier"], note["project_id"], sample_id)
        except Exception as exc:
            logger.exception("note_id=%s failed: %s", note["note_id"], exc)
            stats["errors"] += 1

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
