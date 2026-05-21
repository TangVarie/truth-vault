"""
sanshengliubu-patches/import_truth_vault_baokuan.py
═══════════════════════════════════════════════════════════════════════════

可选 helper, 给 sanshengliubu 自有 codebase 用. **生产飞轮闭环不依赖此 helper
存在**——sync 由 truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py
通过共享 Supabase + service_role 跨 schema INSERT 完成.

这个 helper 的存在意义:
1. sanshengliubu 自己的 ETL / 重导工具想读 Truth Vault 数据时复用列名 +
   quality_score 计算逻辑
2. 集成测试可以用本 helper 模拟 TV 写入

部署:
1. 把本文件内容复制到 sanshengliubu/db/supabase_client.py 中的 SupabaseClient
   类下作为新方法
2. 或导入: `from sanshengliubu_patches.import_truth_vault_baokuan import build_pack`
3. 必须先跑 001_add_source_tv_note_id.sql

列名以 truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py 的
build_reference_sample() 为准. 如果 sanshengliubu 端 schema 改动 (重命名列等),
本 helper / sync 脚本 / docs/09 三处必须同步更新.
"""

from typing import Any


# tier → quality_score 映射. 见 docs/09-system-integration.md "通道 1 数据映射".
TIER_QUALITY_SCORE = {"爆": 100, "大爆": 200}


# Mirror of sync_truth_vault_baokuan_to_sanshengliubu.py:_PLATFORM_EN_TO_SSLL.
# TV 用英文 canonical key (xiaohongshu)；sanshengliubu UI 用中文显示名 (小红书)
# 且 list_reference_packs 按 platform 精确过滤，必须用 ssll 的中文值否则取不到。
_PLATFORM_EN_TO_SSLL: dict[str, str] = {
    "xiaohongshu": "小红书",
    "douyin":      "抖音",
    "weibo":       "微博",
    "bilibili":    "B站",
    "kuaishou":    "快手",
}


def _platform_for_ssll(en_or_zh: str | None) -> str:
    if not en_or_zh:
        return "小红书"
    return _PLATFORM_EN_TO_SSLL.get(en_or_zh, en_or_zh)


def build_pack(note: dict) -> dict:
    """Build a public.reference_samples row dict from a Truth Vault note row.

    Mirror of truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py:
    build_reference_sample. The two must stay in sync — both target the
    canonical v2 reference_samples schema (post_title / post_body /
    top_comments / platform / category / ai_analysis / quality_score,
    added by sanshengliubu/db/migrations/005_reference_samples_v2.sql).

    note 是一个含以下字段的 dict (truth_vault.notes 主表 + 关联):
        - note_id, project_id, raw_content, tier, intent
        - publish_url, target_audience, hit_blue_keywords
        - platform (默认 'xiaohongshu')
        - top_comments: List[dict{content, comment_role, is_pinned}]
        - brand, category (可由 projects 表 join 拿到)

    Fields TV cares about but reference_samples has no top-level column
    for (brand / source_url / target_audience / hit_blue_keywords) get
    stashed inside ai_analysis under `_truth_vault_*` keys.
    """
    tier = note.get("tier")
    quality_score = TIER_QUALITY_SCORE.get(tier, 0)
    top_comments_raw = note.get("top_comments") or []

    # Shape vibe_rewriter expects: [{"text": ..., "likes": ...}, ...]
    # truth_vault.comments lacks `likes`; we emit text/role/pinned only.
    top_comments = [
        {
            "text": c.get("content"),
            "role": c.get("comment_role"),
            "pinned": bool(c.get("is_pinned")),
        }
        for c in top_comments_raw
        if c.get("content")
    ]

    ai_analysis = {
        "_truth_vault_note_id": note["note_id"],
        "_truth_vault_project_id": note["project_id"],
        "_truth_vault_tier": tier,
        "_truth_vault_intent": note.get("intent"),
        "_truth_vault_quality_score": quality_score,
        "_truth_vault_brand": note.get("brand"),
        "_truth_vault_source_url": note.get("publish_url"),
        "_truth_vault_target_audience": note.get("target_audience"),
        "_truth_vault_hit_blue_keywords": note.get("hit_blue_keywords") or [],
    }

    raw_content = note.get("raw_content") or ""
    synthetic_title = raw_content.split("\n", 1)[0][:80] or "未命名样本"

    return {
        "title": synthetic_title,
        # sanshengliubu list_reference_packs filters `.eq("source_type","pack")`
        # — TV samples must write 'pack' to appear in retrieval. TV origin is
        # still recorded via `tags` + `source_truth_vault_note_id`.
        "source_type": "pack",
        "content_text": raw_content,
        "post_title": synthetic_title,
        "post_body": raw_content,
        "top_comments": top_comments,
        # 中文 display name — matches sanshengliubu's UI + retrieval key.
        "platform": _platform_for_ssll(note.get("platform")),
        "category": note.get("category"),
        "ai_analysis": ai_analysis,
        "quality_score": quality_score,
        "tags": ["truth_vault_sync"] + ([tier] if tier else []),
        "source_truth_vault_note_id": note["note_id"],
    }


def import_truth_vault_baokuan(client: Any, note: dict) -> dict:
    """Insert (or upsert) a TV baokuan into sanshengliubu's reference_samples.

    client: a Supabase client already bound to the sanshengliubu DB.

    Caller is responsible for: ensuring 001_add_source_tv_note_id.sql has run;
    ensuring service_role / appropriate auth; checking for an existing row
    via source_truth_vault_note_id if strict idempotency is required.
    """
    pack = build_pack(note)
    res = client.table("reference_samples").insert(pack).execute()
    return (res.data or [{}])[0]
