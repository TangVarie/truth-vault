-- ════════════════════════════════════════════════════════════════════
-- scripts/verify_supabase_state.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-21 audit followup · 单文件 Supabase 状态自检
--
-- 用法:
--   1. Supabase Dashboard → SQL Editor → New query
--   2. 把整个文件粘进去 → Run
--   3. 拿最后一个 SELECT 输出的状态表 (含 ✅/❌/⚠️ 列), 整个贴回给我
--
-- 假设架构 (D-024 · 共享 Supabase): 单一 Supabase project, 三个 schema:
--   truth_vault   — TV 自己的表
--   autowriter    — autowriter 的表
--   public        — sanshengliubu 的表
--
-- 如果 autowriter / sanshengliubu 在两个独立 Supabase project, 单 project
-- 里只会看到一个 schema 的检查通过, 另一个全 ❌, 我看输出就能判断你的部署
-- 是 "已合并到共享实例" 还是 "还分开".
--
-- 安全: 全部是 SELECT / DDL on pg_temp (per-session). 不修改任何数据.
-- ════════════════════════════════════════════════════════════════════

-- ── 辅助函数: 安全执行 COUNT, 表不存在 / 列不存在时返回 NULL 而不崩 ───────
CREATE OR REPLACE FUNCTION pg_temp.safe_count(sql TEXT)
RETURNS BIGINT AS $$
DECLARE
    cnt BIGINT;
BEGIN
    EXECUTE sql INTO cnt;
    RETURN cnt;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


WITH checks AS (

-- ═════════════════════════════════════════════════════════════════
-- A. Schema 存在性
-- ═════════════════════════════════════════════════════════════════
SELECT
    '01' AS ord, 'A · schema' AS section,
    'truth_vault schema 存在' AS check_name,
    (EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'truth_vault'))::TEXT AS actual,
    'true' AS expected,
    'schemas/notes_v1_2.sql 创建' AS hint
UNION ALL
SELECT '02', 'A · schema',
    'autowriter schema 存在',
    (EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'autowriter'))::TEXT,
    'true',
    'autowriter-migrations/001 创建 (或新部署 autowriter 直接在该 schema)'
UNION ALL
SELECT '03', 'A · schema',
    'public.reference_samples 存在 (sanshengliubu)',
    (to_regclass('public.reference_samples') IS NOT NULL)::TEXT,
    'true',
    'sanshengliubu db/schema.sql 跑过'

-- ═════════════════════════════════════════════════════════════════
-- B. truth_vault 关键表
-- ═════════════════════════════════════════════════════════════════
UNION ALL
SELECT '11', 'B · truth_vault',
    'truth_vault.notes 表存在',
    (to_regclass('truth_vault.notes') IS NOT NULL)::TEXT,
    'true', 'schemas/notes_v1_2.sql'
UNION ALL
SELECT '12', 'B · truth_vault',
    'truth_vault.notes.synced_to_aw_at 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='truth_vault' AND table_name='notes'
          AND column_name='synced_to_aw_at'
    ))::TEXT,
    'true', 'schemas/notes_v1_2.sql'
UNION ALL
SELECT '13', 'B · truth_vault',
    'truth_vault.projects.mapping_to_autowriter_project_id 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='truth_vault' AND table_name='projects'
          AND column_name='mapping_to_autowriter_project_id'
    ))::TEXT,
    'true', '通道 2 sync 需要这一列做 TV → aw 项目映射'
UNION ALL
SELECT '14', 'B · truth_vault',
    'truth_vault.prepublish_evaluations 表存在',
    (to_regclass('truth_vault.prepublish_evaluations') IS NOT NULL)::TEXT,
    'true', 'schemas/notes_v1_2.sql'
UNION ALL
SELECT '15', 'B · truth_vault',
    'prepublish_evaluations partial UNIQUE (autowriter_item_id, evaluator_type) 存在',
    (EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'truth_vault'
          AND c.relname = 'idx_tv_evals_aw_item_evaluator_uniq'
          AND i.indisunique = true
    ))::TEXT,
    'true',
    '2026-05-22 audit P1/P2-4: 防 decision sync 并发写重复; 旧库需要重跑 schemas/notes_v1_2.sql 的相应 CREATE UNIQUE INDEX IF NOT EXISTS 段'

-- ═════════════════════════════════════════════════════════════════
-- C. autowriter schema 配置
-- ═════════════════════════════════════════════════════════════════
UNION ALL
SELECT '21', 'C · autowriter',
    'autowriter.items 表存在',
    (to_regclass('autowriter.items') IS NOT NULL)::TEXT,
    'true', '场景 A 需先跑 autowriter-migrations/001 迁 schema'
UNION ALL
SELECT '22', 'C · autowriter',
    'autowriter.items.external_source 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='autowriter' AND table_name='items' AND column_name='external_source'
    ))::TEXT,
    'true', '跑 autowriter-migrations/002'
UNION ALL
SELECT '23', 'C · autowriter',
    'autowriter.items.external_source_id 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='autowriter' AND table_name='items' AND column_name='external_source_id'
    ))::TEXT,
    'true', '跑 autowriter-migrations/002'
UNION ALL
SELECT '24', 'C · autowriter',
    'autowriter.items.example_label_proposal 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='autowriter' AND table_name='items' AND column_name='example_label_proposal'
    ))::TEXT,
    'true', '跑 autowriter-migrations/003'
UNION ALL
SELECT '25', 'C · autowriter',
    '⚠️ 旧全局 unique index items_external_source_uniq 不存在 (新版应已替换)',
    (NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='autowriter' AND indexname='items_external_source_uniq'
    ))::TEXT,
    'true',
    'false 表示旧版 002 跑过且没自愈. 重跑新版 autowriter-migrations/002 或启动新版 autowriter app'
UNION ALL
SELECT '26', 'C · autowriter',
    '新 per-user unique index items_external_source_per_user_uniq 存在',
    (EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='autowriter' AND indexname='items_external_source_per_user_uniq'
    ))::TEXT,
    'true', '重跑新版 002 或启动新版 autowriter app'

-- ═════════════════════════════════════════════════════════════════
-- D. autowriter RLS policy
-- ═════════════════════════════════════════════════════════════════
UNION ALL
SELECT '31', 'D · autowriter RLS',
    'items_owner policy 存在 (USING user_id = auth.uid())',
    (EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname='autowriter' AND tablename='items' AND policyname='items_owner'
    ))::TEXT,
    'true', '应跟着 schema 自动建; 没的话 autowriter db.py bootstrap 会建'
UNION ALL
SELECT '32', 'D · autowriter RLS',
    'batches_owner policy 存在',
    (EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname='autowriter' AND tablename='batches' AND policyname='batches_owner'
    ))::TEXT,
    'true', '同上'

-- ═════════════════════════════════════════════════════════════════
-- E. sanshengliubu (public) schema 配置
-- ═════════════════════════════════════════════════════════════════
UNION ALL
SELECT '41', 'E · sanshengliubu',
    'public.reference_samples v2 列 post_title 存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='reference_samples' AND column_name='post_title'
    ))::TEXT,
    'true', 'sanshengliubu db/migrations/005_reference_samples_v2.sql'
UNION ALL
SELECT '42', 'E · sanshengliubu',
    'public.reference_samples.source_truth_vault_note_id 列存在',
    (EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='reference_samples' AND column_name='source_truth_vault_note_id'
    ))::TEXT,
    'true', 'sanshengliubu-patches/001 (新版 sanshengliubu 已 baked 进 schema.sql)'
UNION ALL
SELECT '43', 'E · sanshengliubu',
    'source_truth_vault_note_id partial unique index 存在 (任一命名)',
    (EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='public'
          AND indexname IN ('idx_reference_samples_tv_note',
                            'idx_reference_samples_tv_note_id_unique')
    ))::TEXT,
    'true', '老命名 (001 patch) 或新命名 (schema.sql 内置) 都行'
UNION ALL
SELECT '44', 'E · sanshengliubu',
    '上面的 index 是 UNIQUE 而不是普通 INDEX',
    (EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname IN ('idx_reference_samples_tv_note',
                            'idx_reference_samples_tv_note_id_unique')
          AND i.indisunique = true
    ))::TEXT,
    'true',
    '2026-05-22 audit P1-3: 必须是 partial UNIQUE 防并发重复. false 表示老 001 patch 留下的普通 index, 跑 sanshengliubu-patches/003_strengthen_tv_note_id_unique.sql 升级.'
UNION ALL
SELECT '45', 'E · sanshengliubu',
    '当前 reference_samples 里有没有重复 source_truth_vault_note_id (UNIQUE 前的污染)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM (
            SELECT source_truth_vault_note_id
            FROM public.reference_samples
            WHERE source_truth_vault_note_id IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) > 1
        ) d$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示 UNIQUE 加之前并发跑产生过重复. 在跑 003 之前必须手工 dedupe.'

-- ═════════════════════════════════════════════════════════════════
-- F. 数据状态 — 飞轮在转吗?
--    用 pg_temp.safe_count 包动态 SQL, 表不存在返回 NULL 而不崩
-- ═════════════════════════════════════════════════════════════════
UNION ALL
SELECT '51', 'F · 数据状态',
    'TV notes 总数 (tier IN 爆/大爆)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes WHERE tier IN ('爆','大爆')$q$
    )::TEXT, 'N/A'),
    '> 0', '没有的话先跑 sync_feishu_notes_to_truth_vault.py'
UNION ALL
SELECT '52', 'F · 数据状态',
    'TV notes 已 sync 到 sanshengliubu (synced_to_ssll_at NOT NULL)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes WHERE synced_to_ssll_at IS NOT NULL$q$
    )::TEXT, 'N/A'),
    '> 0', 'python scripts/sync_truth_vault_baokuan_to_sanshengliubu.py'
UNION ALL
SELECT '53', 'F · 数据状态',
    'TV notes 已 sync 到 autowriter (synced_to_aw_at NOT NULL)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes WHERE synced_to_aw_at IS NOT NULL$q$
    )::TEXT, 'N/A'),
    '> 0', 'python scripts/sync_truth_vault_baokuan_to_autowriter_items.py'
UNION ALL
SELECT '54', 'F · 数据状态',
    'public.reference_samples 里 source_type=pack 总行数',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM public.reference_samples WHERE source_type='pack'$q$
    )::TEXT, 'N/A'),
    '应包含 TV-injected + 自建', 'sanshengliubu vibe_rewriter 取样池'
UNION ALL
SELECT '55', 'F · 数据状态',
    'public.reference_samples 里 source_type=truth_vault_sync 遗留行 (旧值)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM public.reference_samples WHERE source_type='truth_vault_sync'$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示历史行没 backfill, 跑 sanshengliubu-patches/002_widen_pack_filter_backfill.sql'
UNION ALL
SELECT '56', 'F · 数据状态',
    'public.reference_samples 里 TV-tagged 但 platform=xiaohongshu 的遗留行',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM public.reference_samples
        WHERE 'truth_vault_sync' = ANY(tags) AND platform='xiaohongshu'$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示历史行没 backfill, 同上跑 sanshengliubu-patches/002'
UNION ALL
SELECT '57', 'F · 数据状态',
    'autowriter.items 里 external_source=truth_vault 总数',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.items WHERE external_source='truth_vault'$q$
    )::TEXT, 'N/A'),
    '> 0', '为 0 但 #53 > 0 表示通道 2 写入端漂移'
UNION ALL
SELECT '58', 'F · 数据状态',
    'autowriter.items TV-synced 行 user_id ≠ projects.owner_id 的数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.items i
        JOIN autowriter.batches  b ON b.id = i.batch_id
        JOIN autowriter.projects p ON p.id = b.project_id
        WHERE i.external_source='truth_vault'
          AND p.owner_id IS NOT NULL AND p.owner_id <> i.user_id$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示历史 service-account user_id 没 backfill, 跑 autowriter-migrations/006_backfill_tv_synced_user_id.sql'
UNION ALL
SELECT '59', 'F · 数据状态',
    'autowriter.batches 里 tactic=truth_vault_synced 的批次数',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.batches WHERE tactic='truth_vault_synced'$q$
    )::TEXT, 'N/A'),
    '= 已 sync 的 aw project 数', '每个 aw project 一个 special batch'
UNION ALL
SELECT '60', 'F · 数据状态',
    'autowriter.items 里 example_label=positive 的总数',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.items WHERE example_label='positive'$q$
    )::TEXT, 'N/A'),
    '> 0', '为 0 时 list_example_items 取不到 positive examples'

-- ── G · 跨 schema mapping 完整性 (2026-05-22 audit P0 补) ──────────────
-- TV → autowriter / sanshengliubu 的 mapping 字段是手工填的, 错填会让 sync
-- 静默落后某个项目. 这几行检查会立刻显示哪个 TV project 配置有问题.
UNION ALL
SELECT '70', 'G · mapping 完整性',
    'TV projects 里指向无效 autowriter project 的 mapping 数量 (aw 不存在 OR owner_id NULL)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.projects tvp
        LEFT JOIN autowriter.projects awp ON awp.id::TEXT = tvp.mapping_to_autowriter_project_id
        WHERE tvp.mapping_to_autowriter_project_id IS NOT NULL
          AND (awp.id IS NULL OR awp.owner_id IS NULL)$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示某个 mapping 填错或对应 aw project 没初始化 owner. 跑下面 SQL 看具体哪个: '
    'SELECT id, brand, mapping_to_autowriter_project_id FROM truth_vault.projects WHERE ...'
UNION ALL
SELECT '71', 'G · mapping 完整性',
    'TV projects 里指向不存在的 sanshengliubu project 的 mapping 数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.projects tvp
        LEFT JOIN public.projects sslp ON sslp.id::TEXT = tvp.mapping_to_sanshengliubu_project_id
        WHERE tvp.mapping_to_sanshengliubu_project_id IS NOT NULL
          AND sslp.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示某个 mapping 填错. 看 truth_vault.projects 表手工修.'

-- ── H · 跨 schema 孤儿引用检测 (2026-05-22 audit P0 补) ────────────────
-- PG 不支持跨 schema FK ON DELETE 联动. 如果有人在 aw / ssll 删了一行,
-- TV 这边的 source_*_id 就成孤儿, cross-schema view 静默 JOIN 失败.
-- 这两行检查会暴露隐藏的数据完整性问题.
UNION ALL
SELECT '80', 'H · 跨 schema 孤儿',
    'truth_vault.notes.source_autowriter_item_id 指向不存在的 autowriter.items 数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes n
        LEFT JOIN autowriter.items i ON i.id = n.source_autowriter_item_id
        WHERE n.source_autowriter_item_id IS NOT NULL AND i.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示 aw item 被删/UUID 变了; v_model_comparison 等 view 会少行. '
    '修法: 找具体行 UPDATE notes SET source_autowriter_item_id=NULL 或重新 sync.'
UNION ALL
SELECT '81', 'H · 跨 schema 孤儿',
    'truth_vault.notes.source_autowriter_version_id 指向不存在的 autowriter.versions 数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes n
        LEFT JOIN autowriter.versions v ON v.id = n.source_autowriter_version_id
        WHERE n.source_autowriter_version_id IS NOT NULL AND v.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示 aw version 被删. 同 #80 处理.'
UNION ALL
SELECT '82', 'H · 跨 schema 孤儿',
    'truth_vault.notes.source_sanshengliubu_output_id 指向不存在的 public.outputs 数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes n
        LEFT JOIN public.outputs o ON o.id = n.source_sanshengliubu_output_id
        WHERE n.source_sanshengliubu_output_id IS NOT NULL AND o.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示 ssll output 被删. 同 #80 处理.'
UNION ALL
SELECT '83', 'H · 跨 schema 孤儿',
    'truth_vault.note_feature_answers (subject_type=note) 指向不存在的 notes 数量 (D-065: 不建 FK, 靠这里查)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN truth_vault.notes n ON n.note_id = a.subject_id
        WHERE a.subject_type = 'note' AND n.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示笔记被删而答案还在. 修法: DELETE FROM note_feature_answers WHERE subject_type=''note'' AND subject_id NOT IN (SELECT note_id FROM notes).'
UNION ALL
SELECT '84', 'H · 跨 schema 孤儿',
    'truth_vault.note_feature_answers (subject_type=aw_version) 指向不存在的 autowriter.versions 数量',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN autowriter.versions v ON v.id::TEXT = a.subject_id
        WHERE a.subject_type = 'aw_version' AND v.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示写作台版本被删. 同 #83 处理.'
UNION ALL
SELECT '85', 'H · 跨 schema 孤儿',
    'truth_vault.note_feature_answers (subject_type=comment) 指向不存在的 comments 数量 (v1.17 / D-085)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN truth_vault.comments c ON c.comment_id = a.subject_id
        WHERE a.subject_type = 'comment' AND c.comment_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 多半是 D-085 清理删了旧的并行评论行而 judge 的判分还在. 同一批 comment_id 的账本行一起删 (见 sync_comments_from_raw_extra.py 模块头).'
UNION ALL
SELECT '86', 'H · 跨 schema 孤儿',
    'truth_vault.note_feature_answers (subject_type=external_note) 指向不存在的 external_notes 数量 (v1.18)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN truth_vault.external_notes e ON e.note_id = a.subject_id
        WHERE a.subject_type = 'external_note' AND e.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示外部笔记行没写进来 (judge 仓 apply_rows 先写 external_notes 再写账本) 或被删. N/A = v1.18 还没 apply.'
UNION ALL
SELECT '87', 'H · 跨 schema 孤儿',
    'note_feature_answers 近 30 天里 "同一跑 (run_tag × extractor × bank_version) 下行数少于该跑最大值" 的 subject 数 (#86 的反向: 半写)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM (
            SELECT run_tag, extractor, bank_version, subject_id, COUNT(*) AS n,
                   MAX(COUNT(*)) OVER (PARTITION BY run_tag, extractor, bank_version) AS n_max
            FROM truth_vault.note_feature_answers
            WHERE extracted_at > now() - interval '30 days'
            GROUP BY run_tag, extractor, bank_version, subject_id
        ) s WHERE n < n_max$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 多半是 judge 仓 postgrest_upsert 写到一半失败 (PostgREST 批之间没有事务; 2026-10-09 起 judge 回 write_error 带已写行数, '
    'TV 审计 B-06). 修法: 拿当时 /judge 回包里的 ledger_rows 重跑 (upsert 幂等). 也可能是同一 bank_version 中途改了题数——'
    '那种情况 subject 数会很大且集中在一天, 对照 banks/ 的 git log.'

UNION ALL
SELECT '88', 'H · 跨 schema 孤儿',
    'TV notes 的 source_autowriter_version_id 或 source_autowriter_item_id 指向【从 TV 补录进 aw 的副本】(batches.params.source = ingest) 的篇数 (血缘倒挂, 审计 A-02; 两列都看)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*)
        FROM truth_vault.notes n
        LEFT JOIN autowriter.versions v ON v.id = n.source_autowriter_version_id
        LEFT JOIN autowriter.items i ON i.id = COALESCE(n.source_autowriter_item_id, v.item_id)
        LEFT JOIN autowriter.batches b ON b.id = i.batch_id
        WHERE COALESCE(b.params->>'source', '') = 'ingest'$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 补录副本又进了对照索引 (aw store.versions_for_linking 该排除 is_ingest_batch; 2026-10-09 D-099 清过 31 篇, '
    '备份在 truth_vault.backup_inverted_lineage_20261009, 两列都备了). 修法: 先修 aw 再【两列一起】置空, 别反过来, 否则当晚 tv-sync 又填回来.'

UNION ALL
SELECT '89', 'H · 跨 schema 孤儿',
    'TV notes 血缘两列不一致的篇数: 一列空一列不空, 或 item_id ≠ 该 version 所属的 item (D-064 的 COALESCE 回填只补空列, 单清一列会留下错配)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*)
        FROM truth_vault.notes n
        LEFT JOIN autowriter.versions v ON v.id = n.source_autowriter_version_id
        WHERE (n.source_autowriter_item_id IS NULL) <> (n.source_autowriter_version_id IS NULL)
           OR (v.id IS NOT NULL AND n.source_autowriter_item_id <> v.item_id)$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 有人只改了血缘的一列 (codex review on #170 抓到的形态). 修法: 按 version 反查 item 补齐, 或两列一起置空再让 tv-sync 重对.'

UNION ALL
SELECT '91', 'H · 跨 schema 孤儿',
    'prepublish_evaluations 里 evaluator_type=human 且 evaluator_id = 稿件作者 (autowriter.items.user_id) 的行数 (作者自审; 审计 A-01 / D-102: 这些不能当人审真值)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*)
        FROM truth_vault.prepublish_evaluations e
        JOIN autowriter.items i ON i.id = e.autowriter_item_id
        WHERE e.evaluator_type = 'human' AND e.evaluator_id = i.user_id::TEXT$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 要么 aw 侧还没把模型代记的决定改成 human_via_agent (migration 012 + 32 条历史改标), 要么真有人在 Streamlit 里审自己的稿. '
    '前者等 aw 部署; 后者校准时按 D-102 打折.'

UNION ALL
SELECT '92', 'I · 数据一致性',
    '名字带 backup / 日期后缀 (_YYYYMMDD) 且日期已超过 30 天的一次性表个数 (审计 C-17: 一次性表没有过期日)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname IN ('truth_vault', 'autowriter', 'public')
          AND c.relname ~ '(backup|_20[0-9]{6}$)'
          AND substring(c.relname from '_(20[0-9]{6})$') IS NOT NULL
          AND to_date(substring(c.relname from '_(20[0-9]{6})$'), 'YYYYMMDD') < current_date - 30$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 该 drop 了. 每张表的 COMMENT 里有回滚 SQL 和可 drop 日期 (D-086 / D-099 / D-102); 先看注释再 drop, 别顺手删了还没到期的.'

UNION ALL
SELECT '93', 'I · 数据一致性',
    'v_notes_vanished 行数: 盖过 last_seen 戳、但本项目最近一次完整同步没见到的篇 (飞书里删了; 审计 B-21 / D-103)',
    COALESCE(pg_temp.safe_count($q$SELECT COUNT(*) FROM truth_vault.v_notes_vanished$q$)::TEXT, 'N/A'),
    '0',
    '> 0 = 飞书里删了但 TV 还留着 (10-09 实查 HATHERINE 6 · TUGE 4, 全已标 essence、0 在 ssll、0 有经验卡). 新策展 / 通道 1 推送 / 闸二取数 10-09 起自动排除; 已推去 ssll 的样本和已有的经验卡不自动撤 —— 看视图里 synced_to_ssll_at / has_lesson_card 两列, owner 决定删 note 还是留档.'

UNION ALL
SELECT '94', 'H · 跨 schema 孤儿',
    'autowriter.tv_note_links 指向不存在的 truth_vault.notes 的行数 (TV 删了笔记、aw 侧对照没跟着删; codex review on #172)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.tv_note_links l
        LEFT JOIN truth_vault.notes n ON n.note_id = l.note_id
        WHERE n.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 删笔记那一步漏了 aw 侧的对照 (对照没有跨 schema 外键, #83 只盖答案侧, #93 的视图不盖已删的篇). '
    '修法同 D-104: 先 CREATE TABLE autowriter.backup_tv_note_links_<原因>_<日期> AS SELECT 这些行, 再 DELETE FROM autowriter.tv_note_links WHERE note_id NOT IN (SELECT note_id FROM truth_vault.notes).'

-- ── I · 数据一致性副作用 ──────────────────────────────────────────────
UNION ALL
SELECT '90', 'I · 数据一致性',
    'TV projects 里 start_date > end_date 的项目数 (update_project_date_range 竞态)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.projects
        WHERE start_date IS NOT NULL AND end_date IS NOT NULL
          AND start_date > end_date$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示 _common.py:update_project_date_range 撞了 race. '
    '修法: UPDATE projects SET start_date = end_date WHERE start_date > end_date; 再重跑 sync.'

)
SELECT
    ord, section, check_name,
    actual, expected,
    CASE
        WHEN actual = expected THEN '✅'
        WHEN actual = 'N/A' THEN '⚪ 无法判断 (表/schema 缺失)'
        WHEN expected LIKE '> 0%' AND actual ~ '^\d+$' AND actual::INT > 0 THEN '✅'
        WHEN expected = '0' AND actual ~ '^\d+$' AND actual::INT > 0 THEN '⚠️ 需 backfill'
        WHEN expected LIKE '%任一%' THEN '🔍 见提示'
        WHEN actual = 'false' THEN '❌'
        ELSE '🔍'
    END AS status,
    hint
FROM checks
ORDER BY ord;
