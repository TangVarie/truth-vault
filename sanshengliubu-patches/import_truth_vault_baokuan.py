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


def build_pack(note: dict) -> dict:
    """Build a public.reference_samples row dict from a Truth Vault note row.

    note 是一个含以下字段的 dict (truth_vault.notes 主表 + 关联):
        - note_id, project_id, raw_content, tier, intent
        - publish_url, target_audience, hit_blue_keywords
        - platform (默认 'xiaohongshu')
        - top_comments: List[dict{content, comment_role, is_pinned}]
        - brand, category (可由 projects 表 join 拿到)
    """
    tier = note.get("tier")
    quality_score = TIER_QUALITY_SCORE.get(tier, 0)
    top_comments = note.get("top_comments") or []

    ai_analysis = {
        "_truth_vault_note_id": note["note_id"],
        "_truth_vault_project_id": note["project_id"],
        "_truth_vault_tier": tier,
        "_truth_vault_intent": note.get("intent"),
        "_truth_vault_quality_score": quality_score,
        "top_comments": [c.get("content") for c in top_comments if c.get("content")],
        "top_comment_roles": [c.get("comment_role") for c in top_comments],
        "top_comments_pinned": [bool(c.get("is_pinned")) for c in top_comments],
    }

    return {
        "title": (note.get("raw_content") or "")[:60],
        "content": note.get("raw_content"),
        "platform": note.get("platform") or "xiaohongshu",
        "category": note.get("category"),
        "brand": note.get("brand"),
        "source_url": note.get("publish_url"),
        "target_audience": note.get("target_audience"),
        "hit_keywords": note.get("hit_blue_keywords") or [],
        "ai_analysis": ai_analysis,
        "tags": ["truth_vault_sync", tier],
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
