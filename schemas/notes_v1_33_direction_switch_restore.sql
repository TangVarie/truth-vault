-- truth_vault v1.33 · 方向改成抬不了的值之后: 备份 + content_format 回到 essence 的判断 (I-17 Step 2, 2026-11-25)
-- owner 在 SQL editor 跑, 一次跑完整个文件。请在合并 I-17 的代码【之前】跑 (合并后第一次夜跑会清人群 / 痛点, 要先有备份)。
-- ════════════════════════════════════════════════════════════════════
-- 背景: 11-21 运营把 BJS_phase2 的「方向」改成多选, 加了 成人款 / 儿童款 两个款式标。64 篇的方向只剩一个款式标,
--   查不到方向, 同步就不抬了 —— 可人群 / 痛点 / 产品焦点 / content_format 在 UPSERT_PROTECTED_COLS 里, 不送就留着,
--   于是这些篇一直挂着旧方向抬上来的值。HATHERINE 9 月下旬起用了一套新方向名, 也有 6 篇这样。
-- 改什么 (只改这一件): content_format 换回 essence 最后一次写的值。条件全满足才换:
--   · 项目是 BJS_phase2 / HATHERINE_phase1 / SPX_phase1, 现在的方向 (去掉 成人款 / 儿童款) 抬不了;
--   · audit_log 里最后一次改方向之前的那个方向抬得了, 而且库里的 content_format 正好等于它抬的值;
--   · essence 最后一次写这一篇 (audit_log 里带 essence_annotated_at 的 UPDATE) 改过 content_format —— 就换成它改成的值。
--   生产 11-25 只读: 33 篇, 全在 BJS_phase2 (场景植入 → 情感叙事 23 / 认知重构 6 / 直给推荐 3 / 反差破圈 1)。
--   另有 27 篇 (BJS_phase2 23、HATHERINE 4) 也是旧方向的值, 但 essence 那一次没改 content_format (它的判断和当时的值一样),
--   推不出别的值, 不动。
-- 不在这里改、但先备份的: 人群 / 痛点 / 产品焦点。合并后第一次夜跑由同步送 None 清掉 (BJS_phase2 62、HATHERINE 6、
--   SPX_phase1 1, 共 69 篇); 内容层同一晚补上 61 篇 (BJS_phase2 「提问贴 + 款」58 篇 → Q, 「精品贴 + 成人款」3 篇 → J)。
-- 备份: truth_vault.backup_notes_i17_20261125, 每篇一行: 四列 (content_format / target_audience / user_pain_point /
--   product_focus) + content_layer + 方向原值 + 为什么进来。只补没备份过的篇, 重跑不覆盖第一次的值。
--   回滚 SQL 在表的 COMMENT 里 (只想找回人群 / 痛点 / 产品焦点时, 去掉 content_format 那一项, 见 COMMENT)。
--   按 D-136 留着不删; 已登记在 docs/backup-registry.md (verify #92), 你不用做什么。表开 RLS、收回 anon / authenticated 的权限 (verify #92b)。
-- 安全重跑: 换过的篇 content_format 已经不等于旧方向的值, 再跑认不到; 清过的篇三列都是空, 不再进备份。跑几遍结果一样。
-- 前提: v1_24 跑过 (notes.content_layer; 生产已跑)。下面两张小表 (哪些方向抬得了 / 哪些标要忽略) 和
--   mappings/*.yaml 逐条一致, CI 的 scripts/check_direction_switch.py 守着。
-- 跑完看最后的回读: 第一次跑 restored_now 33、left_to_restore 0; 备份 69 篇 (要清三列的 69 篇, 换 content_format 的 33 篇都在里面),
--   其中 reason 带 content_format_restore 的 33 篇。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 0. 哪些方向抬得了 (direction_decomposition 里写了要抬的列、没有 sub_directions) / 哪些标要忽略 ─────────
CREATE TEMP TABLE i17_lifts (project_id text, dir_key text, content_format text) ON COMMIT DROP;
INSERT INTO i17_lifts VALUES
    ('BJS_phase2', '好物分享-产品贴', '场景植入'),
    ('BJS_phase2', '提问贴', '提问求助'),
    ('HATHERINE_phase1', '产品-全家桶', '直给推荐'),
    ('HATHERINE_phase1', '产品-76贴囤货', '直给推荐'),
    ('HATHERINE_phase1', '产品-功能说明', '教程攻略'),
    ('HATHERINE_phase1', '流量-不破皮痘', '场景植入'),
    ('HATHERINE_phase1', '产品-微针', '直给推荐'),
    ('HATHERINE_phase1', '产品-oly上架', '横评对比'),
    ('HATHERINE_phase1', '流量-破皮痘', '场景植入'),
    ('HATHERINE_phase1', '产品-对比', '横评对比'),
    ('SPX_phase1', '提问贴', '提问求助'),
    ('SPX_phase1', '好物分享-产品贴', '场景植入');
CREATE TEMP TABLE i17_ign (project_id text, tok text) ON COMMIT DROP;
INSERT INTO i17_ign VALUES ('BJS_phase2', '成人款'), ('BJS_phase2', '儿童款');

-- 方向原值 → 查表的键 (同 _common.effective_direction_key: 多选按顺序拼 ", ", 去掉要忽略的标; 单值原样)
CREATE OR REPLACE FUNCTION pg_temp.i17_key(project text, dir jsonb) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE jsonb_typeof(dir)
        WHEN 'array' THEN coalesce((
            SELECT string_agg(btrim(e.v), ', ' ORDER BY e.o)
            FROM jsonb_array_elements_text(dir) WITH ORDINALITY AS e(v, o)
            WHERE btrim(e.v) <> ''
              AND NOT EXISTS (SELECT 1 FROM i17_ign i WHERE i.project_id = project AND i.tok = btrim(e.v))), '')
        WHEN 'string' THEN dir #>> '{}'
    END
$$;

-- ── 1. 现在方向抬不了的篇 ─────────────────────────────────────────────
CREATE TEMP TABLE i17_unl ON COMMIT DROP AS
SELECT n.note_id, n.project_id, n.content_format, n.target_audience, n.user_pain_point, n.product_focus,
       n.content_layer, n.raw_extra -> '_direction_raw' AS direction_raw
FROM truth_vault.notes n
WHERE n.project_id IN ('BJS_phase2', 'HATHERINE_phase1', 'SPX_phase1')
  AND n.raw_extra ? '_direction_raw'
  AND NOT EXISTS (SELECT 1 FROM i17_lifts l
                  WHERE l.project_id = n.project_id
                    AND l.dir_key = pg_temp.i17_key(n.project_id, n.raw_extra -> '_direction_raw'));

-- ── 2. 要换回 essence content_format 的篇 ─────────────────────────────────
CREATE TEMP TABLE i17_restore ON COMMIT DROP AS
WITH prev AS (          -- 最后一次改方向之前的方向
    SELECT DISTINCT ON (a.row_id) a.row_id, a.changed_cols -> 'raw_extra' -> 0 -> '_direction_raw' AS old_dir
    FROM truth_vault.audit_log a
    JOIN i17_unl u ON u.note_id = a.row_id
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
      AND a.changed_cols ? 'raw_extra'
      AND (a.changed_cols -> 'raw_extra' -> 0 -> '_direction_raw')
          IS DISTINCT FROM (a.changed_cols -> 'raw_extra' -> 1 -> '_direction_raw')
    ORDER BY a.row_id, a.occurred_at DESC, a.audit_id DESC
),
need AS (               -- 旧方向抬得了, 库里的值正好是它抬的
    SELECT u.note_id, u.project_id, u.content_format AS old_cf
    FROM i17_unl u
    JOIN prev p ON p.row_id = u.note_id
    JOIN i17_lifts l ON l.project_id = u.project_id AND l.dir_key = pg_temp.i17_key(u.project_id, p.old_dir)
    WHERE u.content_format IS NOT DISTINCT FROM l.content_format
),
ess AS (                -- essence 最后一次写这一篇
    SELECT DISTINCT ON (a.row_id) a.row_id,
           a.changed_cols ? 'content_format' AS has_cf,
           a.changed_cols -> 'content_format' ->> 1 AS ess_cf
    FROM truth_vault.audit_log a
    JOIN need n ON n.note_id = a.row_id
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
      AND a.changed_cols ? 'essence_annotated_at'
    ORDER BY a.row_id, a.occurred_at DESC, a.audit_id DESC
)
SELECT n.note_id, n.project_id, n.old_cf, e.ess_cf
FROM need n JOIN ess e ON e.row_id = n.note_id
WHERE e.has_cf AND e.ess_cf IS DISTINCT FROM n.old_cf;

SELECT 'before' AS step, project_id, count(*) AS to_restore FROM i17_restore GROUP BY 1, 2 ORDER BY 2;
SELECT 'before' AS step, project_id, count(*) AS profile_to_clear_next_nightly
FROM i17_unl WHERE target_audience IS NOT NULL OR user_pain_point IS NOT NULL OR product_focus IS NOT NULL
GROUP BY 1, 2 ORDER BY 2;

-- ── 3. 备份 (只补没备份过的篇) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.backup_notes_i17_20261125 AS
SELECT note_id, project_id, content_format, target_audience, user_pain_point, product_focus, content_layer,
       raw_extra -> '_direction_raw' AS direction_raw, ''::text AS reason, now() AS backed_up_at
FROM truth_vault.notes WHERE false;
ALTER TABLE truth_vault.backup_notes_i17_20261125 ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON truth_vault.backup_notes_i17_20261125 FROM %I', r);
        END IF;
    END LOOP;
END $$;
INSERT INTO truth_vault.backup_notes_i17_20261125
SELECT u.note_id, u.project_id, u.content_format, u.target_audience, u.user_pain_point, u.product_focus, u.content_layer,
       u.direction_raw,
       concat_ws('+',
           CASE WHEN r.note_id IS NOT NULL THEN 'content_format_restore' END,
           CASE WHEN u.target_audience IS NOT NULL OR u.user_pain_point IS NOT NULL OR u.product_focus IS NOT NULL
                THEN 'profile_clear_next_nightly' END),
       now()
FROM i17_unl u
LEFT JOIN i17_restore r ON r.note_id = u.note_id
WHERE (r.note_id IS NOT NULL
       OR u.target_audience IS NOT NULL OR u.user_pain_point IS NOT NULL OR u.product_focus IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_notes_i17_20261125 b WHERE b.note_id = u.note_id);

COMMENT ON TABLE truth_vault.backup_notes_i17_20261125 IS
    'I-17 Step 2 (v1_33, 2026-11-25): 方向改成抬不了的值之后, 改之前的 content_format / target_audience / user_pain_point / '
    'product_focus / content_layer。reason: content_format_restore = 本文件换回了 essence 的值; profile_clear_next_nightly = '
    '合并后第一次夜跑清人群 / 痛点 / 产品焦点。回滚: UPDATE truth_vault.notes n SET content_format = b.content_format, '
    'target_audience = b.target_audience, user_pain_point = b.user_pain_point, product_focus = b.product_focus '
    'FROM truth_vault.backup_notes_i17_20261125 b WHERE n.note_id = b.note_id; (I-17 的同步代码还在的话, 下一晚会再清一次三列。) '
    '只想找回人群 / 痛点 / 产品焦点 (比如 I-17 的代码回滚了) 就去掉 SET 里 content_format 那一项: 整条会连本文件换回的 content_format 一起撤掉 (D-178)。'
    '登记在 docs/backup-registry.md (D-136: 留着, 不删)。';

-- ── 4. 换回 essence 的 content_format ──────────────────────────────────
UPDATE truth_vault.notes n
SET content_format = r.ess_cf
FROM i17_restore r
WHERE n.note_id = r.note_id AND n.content_format IS DISTINCT FROM r.ess_cf;

-- ── 5. 回读 ───────────────────────────────────────────────────────────
SELECT 'after' AS step,
       (SELECT count(*) FROM truth_vault.notes n JOIN i17_restore r ON r.note_id = n.note_id
         WHERE n.content_format IS NOT DISTINCT FROM r.ess_cf) AS restored_now,
       (SELECT count(*) FROM truth_vault.notes n JOIN i17_restore r ON r.note_id = n.note_id
         WHERE n.content_format IS DISTINCT FROM r.ess_cf) AS left_to_restore,
       (SELECT count(*) FROM truth_vault.backup_notes_i17_20261125) AS backup_rows,
       (SELECT count(*) FROM truth_vault.backup_notes_i17_20261125 WHERE reason LIKE '%content_format_restore%') AS backup_restore_rows,
       (SELECT count(*) FROM truth_vault.backup_notes_i17_20261125 WHERE reason LIKE '%profile_clear_next_nightly%') AS backup_profile_rows;

COMMIT;
