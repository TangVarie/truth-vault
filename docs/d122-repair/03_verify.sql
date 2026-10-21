-- 3a 计划里每个(篇, 列)库值 = 计划值。期望 0
SELECT p.col, count(*) AS mismatch
FROM truth_vault.repair_notes_essence_cols_20261020 p
JOIN truth_vault.notes t USING (note_id)
WHERE p.restore_v IS DISTINCT FROM CASE p.col
        WHEN 'content_format'  THEN to_jsonb(t.content_format)
        WHEN 'target_audience' THEN to_jsonb(t.target_audience)
        WHEN 'user_pain_point' THEN to_jsonb(t.user_pain_point)
        ELSE                        to_jsonb(t.product_focus)
      END
GROUP BY 1;

-- 3b emotional_lever 有值、content_format 为空: 全库按项目。期望 0 行(恢复前 744)
SELECT project_id, count(*) AS lever_without_format
FROM truth_vault.notes
WHERE emotional_lever IS NOT NULL AND content_format IS NULL
GROUP BY 1 ORDER BY 2 DESC;

-- 3c 有子方向的篇人群 / 痛点为空。期望 0 行(恢复前 NUC 179)
SELECT project_id, count(*) AS subtype_without_audience_or_pain
FROM truth_vault.notes
WHERE direction_subtype IS NOT NULL AND (target_audience IS NULL OR user_pain_point IS NULL)
GROUP BY 1 ORDER BY 2 DESC;

-- 3d 计划按来源 / 项目摊开(写进 I-16 的实际数)
SELECT project_id, col, restore_src, count(*) AS n,
       count(*) FILTER (WHERE restore_v <> wiped_v) AS differs_from_wiped
FROM truth_vault.repair_notes_essence_cols_20261020
GROUP BY 1, 2, 3 ORDER BY 2, 1, 3;
