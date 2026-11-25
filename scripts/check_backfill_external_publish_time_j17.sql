-- check_backfill_external_publish_time_j17.sql —— scripts/backfill_external_publish_time_j17.sql 的 CI 夹具 (J-17; ci.yml sql job 调,
-- v1_18 跑过之后)。psql -v ON_ERROR_STOP=1 -f scripts/check_backfill_external_publish_time_j17.sql, 在仓库根目录跑 (\ir 相对本文件)。
-- 夹具 note_id 都是合成的 (带 cij17), 最后删干净, 连同备份表。
-- ⚠️ 只在一次性的 CI 库上跑 (库名 tv_ci 开头, 或 tv_repair / tv_full_ci)。它会真跑回填, 最后还照回滚语句把
--    被填的行改回空、DROP 备份表; 连到生产上跑会把 owner 的回填撤掉。所以开头先查库名, 不对就停、什么都不改。
--
-- 守的是 (和 Jev judge/external.py publish_time_from_note_id 同一组向量):
--   · 空的、能解的那一行填成 2020-09-13T12:26:40+00:00 (0x5f5e1000 = 1600000000), 格式和已有的行一样;
--   · 下界正好 2013-01-01 00:00:00 UTC 的 (0x50e22700) 填; 早一秒的 (0x50e226ff) 不填 (Jev 是 ts < 2013 才丢);
--   · 早于 2013 的 (0x4b000000 = 2009-11-15)、晚于抓取 + 1 天的、前 8 位不是十六进制的、已经有值的: 一个字不动;
--   · 正好等于抓取 + 1 天的算在范围里 (Jev 是 ts > 抓取 + 1 天才丢);
--   · 备份表记下被填的行, 回滚语句照着注释跑能把它们改回空;
--   · truth_vault 新表默认给 anon / authenticated 的情况下 (模拟最坏的默认授权), 备份表两个角色都碰不到;
--   · 第二遍跑: 什么都不改, 备份表不多行。
-- 反证 (改坏回填 SQL 之后必须红):
--   · 去掉 ts <= fetched_at + interval '1 day' → 「晚于抓取 + 1 天」那行被填, 红;
--   · 下界写成 > 2013-01-01 → 正好 2013-01-01 那行没填, 红; 写成 >= 2013-01-01 00:00:01 或去掉下界 → 早一秒那行被填, 红;
--   · 去掉 publish_time IS NULL → 已有值的那行被改, 红;
--   · 格式写成 'YYYY-MM-DD HH24:MI:SS' → 「填成 …+00:00」红;
--   · 去掉 REVOKE → 默认授权让客户端角色拿到备份表, 红。

\set ON_ERROR_STOP on
DO $$
BEGIN
    IF NOT (current_database() LIKE 'tv\_ci%' OR current_database() IN ('tv_repair', 'tv_full_ci')) THEN
        RAISE EXCEPTION 'J-17 夹具只在一次性的 CI 库上跑, 现在连的是 %: 停, 什么都没改', current_database();
    END IF;
END $$;

DELETE FROM truth_vault.external_notes WHERE note_id LIKE '%cij17%' OR note_id = '5f5e1';
DROP TABLE IF EXISTS truth_vault.backup_external_publish_time_j17_20261125;
ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault REVOKE SELECT, INSERT ON TABLES FROM anon, authenticated;

INSERT INTO truth_vault.external_notes (note_id, category, keyword, body, run_id, fetched_at, publish_time) VALUES
    ('5f5e1000cij17valid',  'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),
    ('50e22700cij17floor',  'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),   -- 正好 2013-01-01 00:00:00 UTC
    ('50e226ffcij17prefl',  'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),   -- 早一秒
    ('4b000000cij17pre13',  'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),
    ('5f5e1000cij17future', 'ci', 'ci', 'x', 'ci-j17', '2020-09-12 12:26:39+00', NULL),
    ('5f5e1000cij17edge',   'ci', 'ci', 'x', 'ci-j17', '2020-09-12 12:26:40+00', NULL),
    ('zz5e1000cij17nonhex', 'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),
    ('5f5e1',               'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', NULL),   -- 不足 8 位
    ('5f5e1000cij17filled', 'ci', 'ci', 'x', 'ci-j17', '2026-11-03 00:00:00+00', '2021-01-01');

-- 模拟最坏的默认授权: truth_vault 下新建的表默认给客户端角色 (生产没有; 这样回填 SQL 的 REVOKE 才真被考到)
ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault GRANT SELECT, INSERT ON TABLES TO anon, authenticated;
\ir backfill_external_publish_time_j17.sql
ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault REVOKE SELECT, INSERT ON TABLES FROM anon, authenticated;

DO $$
DECLARE
    got jsonb;
BEGIN
    SELECT jsonb_object_agg(note_id, publish_time) INTO got
      FROM truth_vault.external_notes WHERE note_id LIKE '%cij17%' OR note_id = '5f5e1';
    IF got->>'5f5e1000cij17valid' IS DISTINCT FROM '2020-09-13T12:26:40+00:00' THEN
        RAISE EXCEPTION 'J-17: 能解的那行应填成 2020-09-13T12:26:40+00:00, 实际 %', got->>'5f5e1000cij17valid';
    END IF;
    IF got->>'5f5e1000cij17edge' IS DISTINCT FROM '2020-09-13T12:26:40+00:00' THEN
        RAISE EXCEPTION 'J-17: 正好等于抓取 + 1 天的应算在范围里, 实际 %', got->>'5f5e1000cij17edge';
    END IF;
    IF got->>'50e22700cij17floor' IS DISTINCT FROM '2013-01-01T00:00:00+00:00' THEN
        RAISE EXCEPTION 'J-17: 正好 2013-01-01 00:00:00 UTC 的应算在范围里 (下界含), 实际 %', got->>'50e22700cij17floor';
    END IF;
    IF got->>'4b000000cij17pre13' IS NOT NULL OR got->>'5f5e1000cij17future' IS NOT NULL
       OR got->>'zz5e1000cij17nonhex' IS NOT NULL OR got->>'5f5e1' IS NOT NULL OR got->>'50e226ffcij17prefl' IS NOT NULL THEN
        RAISE EXCEPTION 'J-17: 早于 2013 (含早一秒) / 晚于抓取 + 1 天 / 不是十六进制 / 不足 8 位的应留空: %', got;
    END IF;
    IF got->>'5f5e1000cij17filled' IS DISTINCT FROM '2021-01-01' THEN
        RAISE EXCEPTION 'J-17: 已经有值的行不许动, 实际 %', got->>'5f5e1000cij17filled';
    END IF;
    IF (SELECT count(*) FROM truth_vault.backup_external_publish_time_j17_20261125 WHERE note_id LIKE '%cij17%')
       IS DISTINCT FROM 3::bigint THEN
        RAISE EXCEPTION 'J-17: 备份表应正好记下被填的 3 行';
    END IF;
    IF coalesce(col_description('truth_vault.external_notes'::regclass,
           (SELECT attnum FROM pg_attribute WHERE attrelid = 'truth_vault.external_notes'::regclass AND attname = 'publish_time')), '')
       NOT LIKE '%note_id%' THEN
        RAISE EXCEPTION 'J-17: publish_time 的列注释没写从 note_id 解';
    END IF;
    IF has_table_privilege('anon', 'truth_vault.backup_external_publish_time_j17_20261125',
                           'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
       OR has_table_privilege('authenticated', 'truth_vault.backup_external_publish_time_j17_20261125',
                              'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER') THEN
        RAISE EXCEPTION 'J-17: 默认授权下, 备份表 anon / authenticated 还有权限 (REVOKE 没起作用)';
    END IF;
END $$;

-- 第二遍: 什么都不改
CREATE TEMP TABLE _j17_before AS SELECT note_id, publish_time FROM truth_vault.external_notes WHERE note_id LIKE '%cij17%';
\ir backfill_external_publish_time_j17.sql
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM truth_vault.external_notes e JOIN _j17_before b USING (note_id)
                WHERE e.publish_time IS DISTINCT FROM b.publish_time)
       OR (SELECT count(*) FROM truth_vault.backup_external_publish_time_j17_20261125 WHERE note_id LIKE '%cij17%') <> 3 THEN
        RAISE EXCEPTION 'J-17: 第二遍跑不该再改任何东西';
    END IF;
END $$;

-- 回滚语句 (表注释里那一句) 照跑, 被填的三行回到空
UPDATE truth_vault.external_notes e SET publish_time = b.publish_time
  FROM truth_vault.backup_external_publish_time_j17_20261125 b WHERE e.note_id = b.note_id;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM truth_vault.external_notes
                WHERE note_id IN ('5f5e1000cij17valid', '5f5e1000cij17edge', '50e22700cij17floor') AND publish_time IS NOT NULL)
       OR (SELECT publish_time FROM truth_vault.external_notes WHERE note_id = '5f5e1000cij17filled') IS DISTINCT FROM '2021-01-01' THEN
        RAISE EXCEPTION 'J-17: 照注释回滚之后, 被填的三行应回到空、原来有值的不动';
    END IF;
END $$;

DELETE FROM truth_vault.external_notes WHERE note_id LIKE '%cij17%' OR note_id = '5f5e1';
DROP TABLE truth_vault.backup_external_publish_time_j17_20261125;
DROP TABLE _j17_before;
\echo '  ✓ J-17 回填: 能解的填、上下界照 Jev (2013 下界含、抓取 + 1 天上界含)、别的不动、备份 / 授权 / 回滚 / 重跑都对'
