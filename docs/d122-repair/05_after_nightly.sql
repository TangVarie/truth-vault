-- 5a 修复合并之后: 受保护列「非空 → NULL」的 UPDATE。起点是 TV#209 合并时刻 2026-10-20 16:27 UTC, 不用改:
--    合并之后的第一晚是 10-21 那次 daily-sync(cron 02:17 UTC, 实际常拖到 06–09 UTC 才起跑), 之后每一晚也都在范围里。
--    恢复本身(10-20 约 16:35)只把 NULL 写回值, 不会算进来。
--    期望: unexpected 全是 0。四个 essence 列 wipes 也应该是 0。
--    tier / tier_source 有两种是代码故意写的 NULL(payload 里显式带着 None, 修复不挡、也不该挡), 不算 unexpected:
--      · 状态格被清空 → apply_cleared_status 写默认档(规则没有 default 就是 NULL)、tier_source 置空, 旗子 tier_cleared;
--      · 状态格有值但规则一个都没命中 → transform_row 写 tier = NULL(tier_source 还是 状态字段), 旗子 tier_unmapped。
--    旗子看这条 UPDATE 写进去的新值(两种都是当晚打的旗, 和 tier 同一条 UPDATE); 这条没改旗子才看库里现在的。
SELECT c.col,
       count(*) AS wipes,
       count(*) FILTER (WHERE c.col NOT IN ('tier', 'tier_source')
                           OR NOT coalesce(coalesce(a.changed_cols -> 'data_quality_flags' -> 1, n.data_quality_flags)
                                           ?| ARRAY['tier_cleared', 'tier_unmapped'], false)) AS unexpected
FROM truth_vault.audit_log a
CROSS JOIN (VALUES ('content_format'), ('target_audience'), ('user_pain_point'), ('product_focus'),
                   ('tier'), ('tier_source'), ('data_quality_flags'),
                   ('source_autowriter_item_id'), ('source_autowriter_version_id'),
                   ('last_seen_at'), ('last_seen_run_id')) c(col)
LEFT JOIN truth_vault.notes n ON n.note_id = a.row_id
WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
  AND a.occurred_at > timestamptz '2026-10-20 16:27:00+00'   -- TV#209 合并时刻; 包含 10-21 那一晚
  AND a.changed_cols -> c.col -> 0 <> 'null'::jsonb
  AND a.changed_cols -> c.col -> 1 = 'null'::jsonb
GROUP BY 1 ORDER BY 1;

-- 5b emotional_lever 有值、content_format 为空: 应该还是恢复后 3b 的数(理想是 0)
SELECT project_id, count(*) AS lever_without_format
FROM truth_vault.notes
WHERE emotional_lever IS NOT NULL AND content_format IS NULL
GROUP BY 1 ORDER BY 2 DESC;

-- 5c 恢复过的格子: 又成了 NULL 的必须是 0; 被换成别的非空值的只看不判
--    (方向后来映上了、按新方向抬了值, 是对的; 见 REPAIR.md「之后会变的」)
SELECT p.project_id, p.col,
       count(*) FILTER (WHERE cur IS NULL OR cur = 'null'::jsonb)           AS nulled_again,
       count(*) FILTER (WHERE cur <> 'null'::jsonb AND cur <> p.restore_v)  AS changed_to_other
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.notes t USING (note_id)
CROSS JOIN LATERAL (SELECT CASE p.col
        WHEN 'content_format'  THEN to_jsonb(t.content_format)
        WHEN 'target_audience' THEN to_jsonb(t.target_audience)
        WHEN 'user_pain_point' THEN to_jsonb(t.user_pain_point)
        ELSE                        to_jsonb(t.product_focus) END AS cur) v
GROUP BY 1, 2
HAVING count(*) FILTER (WHERE cur IS NULL OR cur = 'null'::jsonb) > 0
    OR count(*) FILTER (WHERE cur <> 'null'::jsonb AND cur <> p.restore_v) > 0
ORDER BY 1, 2;
