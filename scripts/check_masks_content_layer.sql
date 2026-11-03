-- check_masks_content_layer.sql —— schemas/notes_v1_24_external_masks_content_layer.sql 的 CI 夹具 (D-140; ci.yml sql job 调,
-- 迁移已经跑过两遍之后)。psql -v ON_ERROR_STOP=1 -f scripts/check_masks_content_layer.sql, 在仓库根目录跑 (\i 用相对路径)。
--
-- 守的是: 内容层只许 P / T / Q / J (NULL 可以); 遮挡行外键到 external_notes、跟着级联删; terms 只许数组; masked_at 有默认值;
-- RLS 开着; 先 GRANT ALL 给 anon / authenticated 再重跑迁移, 两个角色的读写都被撤掉; 重跑迁移不动已有的内容层。
-- 反证: CHECK 写成 IN ('P','T','Q','J','X') → 写 X 不报错, 红; 去掉 ON DELETE CASCADE → 删外部帖报外键错, 红;
--       去掉 REVOKE 那段 → anon 仍有 SELECT, 红; 迁移里加一句 UPDATE notes SET content_layer = NULL → 最后一段红。

INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('CI_V24', 'b', 'p', '保健品');
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, content_layer) VALUES
    ('CI_V24_p', 'CI_V24', '正文', 'P'), ('CI_V24_null', 'CI_V24', '正文', NULL);
INSERT INTO truth_vault.external_notes (note_id, category, keyword, body, run_id) VALUES ('ci_v24_ext', '鼻炎', 'k', '正文', 'r');
INSERT INTO truth_vault.external_note_masks (note_id, terms, text_sha, model)
    VALUES ('ci_v24_ext', '[{"t": "BrandX", "k": "品牌"}]', 'sha', 'm');

DO $$
BEGIN
    BEGIN
        UPDATE truth_vault.notes SET content_layer = 'X' WHERE note_id = 'CI_V24_p';
        RAISE EXCEPTION 'v1.24: content_layer 写进了 X (CHECK 没起作用)';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO truth_vault.external_note_masks (note_id, terms, text_sha) VALUES ('ci_v24_ext2', '[]', 's');
        RAISE EXCEPTION 'v1.24: 外部表里没有的帖也写进了遮挡表 (外键没起作用)';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE truth_vault.external_note_masks SET terms = '{"t": "x"}' WHERE note_id = 'ci_v24_ext';
        RAISE EXCEPTION 'v1.24: terms 写进了对象 (只许数组)';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    IF (SELECT masked_at FROM truth_vault.external_note_masks WHERE note_id = 'ci_v24_ext') IS NULL THEN
        RAISE EXCEPTION 'v1.24: masked_at 没有默认值';
    END IF;
    DELETE FROM truth_vault.external_notes WHERE note_id = 'ci_v24_ext';
    IF EXISTS (SELECT 1 FROM truth_vault.external_note_masks WHERE note_id = 'ci_v24_ext') THEN
        RAISE EXCEPTION 'v1.24: 外部帖删了, 遮挡行还在 (没有级联)';
    END IF;
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'truth_vault.external_note_masks'::regclass) THEN
        RAISE EXCEPTION 'v1.24: external_note_masks 没开 RLS';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated; END IF;
    GRANT ALL ON truth_vault.external_note_masks TO anon, authenticated;     -- 复现 Supabase 的默认授权, 下面重跑迁移要撤掉
END $$;

\i schemas/notes_v1_24_external_masks_content_layer.sql

DO $$
DECLARE
    bad text;
BEGIN
    SELECT string_agg(r || ':' || p, ',') INTO bad
      FROM unnest(ARRAY['anon', 'authenticated']) r, unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
     WHERE has_table_privilege(r, 'truth_vault.external_note_masks', p);
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'v1.24: 重跑迁移之后这些权限还在: %', bad; END IF;
    SELECT string_agg(note_id || ':' || coalesce(content_layer, '-'), ',' ORDER BY note_id) INTO bad
      FROM truth_vault.notes WHERE project_id = 'CI_V24';
    IF bad IS DISTINCT FROM 'CI_V24_null:-,CI_V24_p:P' THEN RAISE EXCEPTION 'v1.24: 重跑迁移改了已有的内容层 [%]', bad; END IF;
    DELETE FROM truth_vault.notes WHERE project_id = 'CI_V24';
    DELETE FROM truth_vault.projects WHERE project_id = 'CI_V24';
    RAISE NOTICE '✓ v1.24: 内容层只许 P/T/Q/J、NULL 可以; 遮挡行外键 + 级联删 + terms 是数组; RLS 开着; anon / authenticated 读写都撤; 重跑不动已有值';
END $$;
