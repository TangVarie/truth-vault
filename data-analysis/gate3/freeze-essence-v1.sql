-- 闸三第一轨 · 冻结 essence 打分器（D-118）。只读，在生产 SQL editor / MCP 跑一次，输出整份冻结 JSON。
-- 与 gate2_combo.tag_features / gate2_run.analysis_notes 同一口径：
--   训练集 = v_l2_labels ∩ 有 essence ∩ 正文 ≥ 50 字（body_len 未知的不剔）∩ 不在 v_notes_vanished ∩ 发布早于冻结日
--   token = L:情绪杠杆 / F:内容形式 / A:人性原型 / U:目标人群（每篇去重）
--   权重 w = ln((爆 + 1) / (趴 + 1))，全量训练（不留一项目：闸三是对冻结日之后的新笔记打分）
--   分 = 这篇带的、有权重的 token 的权重平均（权重先 round 到 6 位，和 Python 运行时逐位一致）
--   切点 = 冻结日前有 essence 的全部笔记（不只有标签的）按项目算 101 个分位（percentile_cont 0..1 步长 0.01）；
--          不足 50 篇的项目不给项目切点，运行时用全库（pooled）
WITH params AS (SELECT timestamp '2026-10-17 00:00:00' AS freeze_at),
base AS (
  SELECT n.note_id, n.project_id, n.emotional_lever, n.content_format, n.human_truth_archetype, n.target_audience
  FROM truth_vault.notes n LEFT JOIN truth_vault.note_features f USING (note_id), params
  WHERE coalesce(n.emotional_lever, '') <> ''
    AND (f.body_len IS NULL OR f.body_len >= 50)
    AND n.publish_time < params.freeze_at
    AND NOT EXISTS (SELECT 1 FROM truth_vault.v_notes_vanished v WHERE v.note_id = n.note_id)
),
tok AS (
  SELECT DISTINCT note_id, t FROM (
    SELECT note_id, 'L:' || emotional_lever AS t FROM base
    UNION ALL SELECT note_id, 'F:' || content_format FROM base WHERE coalesce(content_format, '') <> ''
    UNION ALL SELECT note_id, 'A:' || x FROM base, unnest(human_truth_archetype) x WHERE coalesce(x, '') <> ''
    UNION ALL SELECT note_id, 'U:' || x FROM base, unnest(target_audience) x WHERE coalesce(x, '') <> ''
  ) z
),
train AS (SELECT b.note_id, b.project_id, l.y FROM base b JOIN truth_vault.v_l2_labels l USING (note_id)),
w AS (
  SELECT k.t, round(ln((sum(tr.y) + 1.0) / (sum(1 - tr.y) + 1.0))::numeric, 6) AS w,
         sum(tr.y) AS pos, sum(1 - tr.y) AS neg
  FROM tok k JOIN train tr USING (note_id) GROUP BY k.t
),
sc AS (
  SELECT b.note_id, b.project_id, round(avg(w.w), 6) AS s
  FROM base b JOIN tok k USING (note_id) JOIN w USING (t) GROUP BY b.note_id, b.project_id
),
proj_raw AS (
  SELECT project_id, count(*) AS n,
         percentile_cont(ARRAY(SELECT g / 100.0 FROM generate_series(0, 100) g)::float8[]) WITHIN GROUP (ORDER BY s) AS q
  FROM sc GROUP BY project_id HAVING count(*) >= 50
),
pooled_raw AS (
  SELECT count(*) AS n,
         percentile_cont(ARRAY(SELECT g / 100.0 FROM generate_series(0, 100) g)::float8[]) WITHIN GROUP (ORDER BY s) AS q
  FROM sc
),
proj AS (
  SELECT project_id, n, (SELECT array_agg(round(v::numeric, 6) ORDER BY o) FROM unnest(q) WITH ORDINALITY u(v, o)) AS q
  FROM proj_raw
),
pooled AS (
  SELECT n, (SELECT array_agg(round(v::numeric, 6) ORDER BY o) FROM unnest(q) WITH ORDINALITY u(v, o)) AS q
  FROM pooled_raw
)
SELECT jsonb_build_object(
  'scorer', 'essence-v1',
  'freeze_publish_time', (SELECT to_char(freeze_at, 'YYYY-MM-DD"T"HH24:MI:SS') FROM params),
  'token_scheme', 'L/F/A/U per gate2_combo.tag_features',
  'weights', (SELECT jsonb_object_agg(t, w ORDER BY t) FROM w),
  'weight_counts', (SELECT jsonb_object_agg(t, jsonb_build_array(pos, neg) ORDER BY t) FROM w),
  'train', jsonb_build_object('notes', (SELECT count(*) FROM train), 'pos', (SELECT sum(y) FROM train),
                              'projects', (SELECT count(DISTINCT project_id) FROM train)),
  'cutpoints', jsonb_build_object(
      'min_project_notes', 50,
      'project', (SELECT jsonb_object_agg(project_id, jsonb_build_object('n', n, 'q', to_jsonb(q)) ORDER BY project_id) FROM proj),
      'pooled', (SELECT jsonb_build_object('n', n, 'q', to_jsonb(q)) FROM pooled))
) AS scorer;
