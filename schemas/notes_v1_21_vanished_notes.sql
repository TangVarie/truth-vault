-- truth_vault v1.21 · v_notes_vanished: 飞书里已经删掉、TV 里还留着的篇 (审计 B-21, D-103, 2026-10-09)
-- ════════════════════════════════════════════════════════════════════
-- 背景: notes_v1_9 的对账只【报】不改 —— 每晚 sync 打一行 "对账: N 条消失" 就过去了, 删掉的篇照样被
--   新策展 (curate_flywheel_lessons) / 通道 1 推送 (sync_truth_vault_baokuan_to_sanshengliubu) / 闸二取数 (gate2_run)
--   当成活的用。10-09 实查: HATHERINE_phase1 6 篇 · TUGE_phase1 4 篇, 全部已推去 ssll 或已标 essence。
-- 判据 (和 sync 的对账同一条, 只是改成跨项目一张视图):
--   「消失」= 盖过 last_seen 戳 (last_seen_run_id 非空)、且 last_seen_run_id ≠ 本项目最近一次完整同步的 run_id。
--   · 比的是【本项目自己】最近一次完整同步 (按 last_seen_at 取最新那条的 run_id), 不是固定天数: on_demand 项目
--     不进夜跑, 用"3 天没见到"会把它们全报成消失;
--   · 从没盖过戳的 (last_seen_run_id IS NULL, 七个 on_demand 项目全是) 不算 —— 那是"还没经历过完整同步", 不是消失;
--   · 戳只在 full_scan 时盖 (sync_feishu_notes_to_truth_vault.py), 所以"最近一次 run"一定是完整扫描;
--   · 残留: 同项目两次完整同步并行时, 只被先跑那次见到的行会在下一次同步前短暂算消失 (sync 的对账有同样的窗口)。
-- 只报不删: 删不删 note、撤不撤已推去 ssll 的样本 / 已有的经验卡, 由 owner 看这张视图定 (回收只认资格, D-087)。
-- 消费者: _common.fetch_vanished_note_ids (三条新生产路径按它排除) · verify_supabase_state.sql #93 · CI check_vanished_notes.py。
-- 在 notes_v1_9 (last_seen 两列) 与 notes_v1_4 (flywheel_lesson_annotations) 之后应用; 只建视图, 幂等。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_notes_vanished AS
WITH latest AS (
    SELECT DISTINCT ON (project_id)
        project_id,
        last_seen_run_id AS latest_run_id,
        last_seen_at     AS latest_seen_at
    FROM truth_vault.notes
    WHERE last_seen_run_id IS NOT NULL
    ORDER BY project_id, last_seen_at DESC
)
SELECT
    n.note_id,
    n.project_id,
    n.tier,
    n.publish_url,
    n.last_seen_run_id,
    n.last_seen_at,
    l.latest_run_id,
    l.latest_seen_at,
    n.synced_to_ssll_at,
    n.synced_to_aw_at,
    n.essence_annotated_at,
    EXISTS (SELECT 1 FROM truth_vault.flywheel_lesson_annotations c WHERE c.note_id = n.note_id) AS has_lesson_card
FROM truth_vault.notes n
JOIN latest l ON l.project_id = n.project_id
WHERE n.last_seen_run_id IS NOT NULL
  AND n.last_seen_run_id <> l.latest_run_id;

COMMENT ON VIEW truth_vault.v_notes_vanished IS
    '飞书里已删、TV 里还留着的篇: 盖过 last_seen 戳但本项目最近一次完整同步没见到 (D-103)。只报不删; 新策展 / 通道 1 / 闸二取数按它排除。';
