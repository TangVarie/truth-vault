-- ════════════════════════════════════════════════════════════════════
-- J-17 · 外部帖旧行的发帖时间回填 (owner 在 Supabase SQL editor 整份跑; D-138)
-- ════════════════════════════════════════════════════════════════════
--
-- 改什么: truth_vault.external_notes 里 publish_time 为空的旧行, 从 note_id 前 8 位十六进制解出发帖时刻写进去。
--   规则和 Jev 的 judge/external.py publish_time_from_note_id 一样 (11-04 起新抓的行就是这么填的):
--     · 前 8 位十六进制 = unix 秒, 写成 UTC, 格式 YYYY-MM-DDTHH:MM:SS+00:00 (和已有的行逐字同格式);
--     · 早于 2013-01-01 的、晚于这一行抓取时间 + 1 天的、前 8 位不是十六进制的: 不写, 留空。
--   另给 publish_time 加一句列注释, 说明它从哪来。
-- 不改什么: 已经有值的行一行不动; 别的列不动; 表上没有用户触发器。没有任何代码读这一列
--   (TV 书架和写作台发牌都自己从 note_id 现解), 所以写进去只是方便在 SQL 里直接看。
--
-- 11-25 生产只读 dry-run (跑之前的数):
--   表里 3,149 行; publish_time 为空 1,419 行 (11-03 及之前那 7 批); 这 1,419 行全部能解, 会被填上
--   (解出来在 2016-05-16 到 2026-11-03 之间); 早于 2013 的 0 行, 晚于抓取 + 1 天的 0 行, 不是十六进制的 0 行。
--   已有值的 1,730 行和这条规则算出来的逐字一样 (所以规则对得上)。
--
-- 备份: 先把要改的行的 note_id 和原值 (都是空) 记进 truth_vault.backup_external_publish_time_j17_20261125。
--   回滚写在这张表的注释里: 把这些行的 publish_time 改回空。备份表已登记在 docs/backup-registry.md (verify #92)。
--
-- 可以重跑: 第二次跑时没有空行可填, 备份表里也不会多行 (按 note_id 去重), 最后的数不变。
-- 跑完看最后一个 SELECT: null_left 应为 0, filled_by_this 应为 1,419 (备份表的行数), rows_total 3,149 左右 (之后新抓的行会让它变多)。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. 备份要改的行
CREATE TABLE IF NOT EXISTS truth_vault.backup_external_publish_time_j17_20261125 (
    note_id      TEXT PRIMARY KEY,
    publish_time TEXT,
    backed_up_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE truth_vault.backup_external_publish_time_j17_20261125 ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON truth_vault.backup_external_publish_time_j17_20261125 FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON truth_vault.backup_external_publish_time_j17_20261125 FROM authenticated;
    END IF;
END $$;
COMMENT ON TABLE truth_vault.backup_external_publish_time_j17_20261125 IS
  'J-17 (2026-11-25) 回填 external_notes.publish_time 之前, 被填的行的原值 (都是空)。回滚: '
  'UPDATE truth_vault.external_notes e SET publish_time = b.publish_time '
  'FROM truth_vault.backup_external_publish_time_j17_20261125 b WHERE e.note_id = b.note_id; '
  '登记在 docs/backup-registry.md (D-136: 留着, 不删)。';

CREATE TEMP TABLE _j17 ON COMMIT DROP AS
SELECT x.note_id,
       to_char(x.ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"') AS new_publish_time
FROM (
    SELECT e.note_id, e.fetched_at,
           CASE WHEN substr(e.note_id, 1, 8) ~ '^[0-9a-fA-F]{8}$'
                THEN to_timestamp(('x' || substr(e.note_id, 1, 8))::bit(32)::bigint) END AS ts
    FROM truth_vault.external_notes e
    WHERE e.publish_time IS NULL
) x
WHERE x.ts IS NOT NULL
  AND x.ts >= timestamptz '2013-01-01 00:00:00+00'
  AND x.ts <= x.fetched_at + interval '1 day';

INSERT INTO truth_vault.backup_external_publish_time_j17_20261125 (note_id, publish_time)
SELECT j.note_id, NULL FROM _j17 j
ON CONFLICT (note_id) DO NOTHING;

-- 2. 回填 (只填空的)
UPDATE truth_vault.external_notes e
SET publish_time = j.new_publish_time
FROM _j17 j
WHERE e.note_id = j.note_id AND e.publish_time IS NULL;

-- 3. 列注释
COMMENT ON COLUMN truth_vault.external_notes.publish_time IS
  '发帖时刻 (文本, UTC)。平台给了就照存; 没给的从 note_id 前 8 位十六进制解出 (unix 秒, 格式 YYYY-MM-DDTHH:MM:SS+00:00; '
  '早于 2013 或晚于抓取 + 1 天的留空)。Jev 11-04 起新行这么填 (J-17, D-138); 之前的旧行由 '
  'scripts/backfill_external_publish_time_j17.sql 回填, 原值在 truth_vault.backup_external_publish_time_j17_20261125。';

COMMIT;

-- 4. 回读
SELECT
    (SELECT count(*) FROM truth_vault.external_notes) AS rows_total,
    (SELECT count(*) FROM truth_vault.external_notes WHERE publish_time IS NULL) AS null_left,
    (SELECT count(*) FROM truth_vault.backup_external_publish_time_j17_20261125) AS filled_by_this,
    (SELECT count(*) FROM truth_vault.external_notes e
       JOIN truth_vault.backup_external_publish_time_j17_20261125 b ON b.note_id = e.note_id
      WHERE e.publish_time IS NULL) AS backed_up_but_still_null;
