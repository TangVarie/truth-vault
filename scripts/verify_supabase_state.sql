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
    '任意 (只是个数)', '不用修: 通道 2 push 已退役 (D-038), 写作台的经验卡走馆员; 这个数不再涨是对的, 不要为了它去跑那个推送脚本'
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
    'truth_vault.note_feature_answers (subject_type=aw_version) 指向不存在的 autowriter.versions 数量 (含 :pN 段级行剥后缀核对)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN autowriter.versions v ON v.id::TEXT = regexp_replace(a.subject_id, ':p[0-9]+$', '')
        WHERE a.subject_type = 'aw_version' AND v.id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 表示写作台版本被删. 同 #83 处理. shadow-human 的段级行 subject_id 形如 <version_id>:pN, 剥掉 :pN 后核对版本是否存在.'
UNION ALL
SELECT '85', 'H · 跨 schema 孤儿',
    'truth_vault.note_feature_answers (subject_type=comment) 指向不存在的 comments 数量 (v1.17 / D-085)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.note_feature_answers a
        LEFT JOIN truth_vault.comments c ON c.comment_id = a.subject_id
        WHERE a.subject_type = 'comment' AND c.comment_id IS NULL
          AND a.subject_id NOT LIKE '%\_lcd%'$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 多半是 D-085 清理删了旧的并行评论行而 judge 的判分还在. 同一批 comment_id 的账本行一起删 (见 sync_comments_from_raw_extra.py 模块头). 不数 id 带 _lcd 的: 那是巡查快照拆出来的读者评论, 快照一变旧行就换掉 (D-155), 判分留着不碍事.'
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
              AND run_tag NOT LIKE 'img-%'
            GROUP BY run_tag, extractor, bank_version, subject_id
        ) s WHERE n < n_max$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 多半是 judge 仓 postgrest_upsert 写到一半失败 (PostgREST 批之间没有事务; 2026-10-09 起 judge 回 write_error 带已写行数, '
    'TV 审计 B-06). 修法: 拿当时 /judge 回包里的 ledger_rows 重跑 (upsert 幂等). 也可能是同一 bank_version 中途改了题数——'
    '那种情况 subject 数会很大且集中在一天, 对照 banks/ 的 git log. '
    '不数首图的行 (run_tag 以 img- 开头, v1.28): 模型说不是封面的帖按规矩只存一行, 封面存十几行, 行数本来就不齐; '
    '它们由 write_first_image_result 在一个事务里写, 没有半写这回事.'

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
    '名字像备份、却没登记的表数 (S-02 / D-136: 备份都留着, 新的要登记; 登记册 docs/backup-registry.md。'
    '名字像备份 = 含 backup、以 _bak_ 加四位数字开头、或以 _YYYYMMDD 结尾; truth_vault.backup_d129_ids_20261026 永久保留, 另外除外)',
    COALESCE(pg_temp.safe_count(
        $q$WITH registered(pat) AS (VALUES
                ('^truth_vault\.backup_d129_ids_20261026$'),
                ('^truth_vault\.backup_(inverted_lineage|(notes|nfa|comments|metric_snapshots)_vanished)_20261009$'),
                ('^autowriter\.backup_(tv_note_links_inverted|items_self_review|tv_note_links_vanished)_20261009$'),
                ('^autowriter\.backup_(tv_note_links_twins|orphan_ingest_tuge)_20261010$'),
                ('^autowriter\.backup_memory_xiwu_contam_20261012$'),
                ('^truth_vault\.(reference_samples_backup_tv_stale|notes_ssll_marker_backup)_20261008$'),
                ('^truth_vault\.backup_quarantine_resolve_20261016$'),
                ('^truth_vault\.backup_gate3_preannotated_2026(1019|1030)$'),
                ('^truth_vault\.(backup|repair)_notes_essence_cols_20261020$'),
                ('^truth_vault\.backup_content_scores_d122_20261020$'),
                ('^autowriter\.backup_(global_shorten_rules|delivery_params)_20261020$'),
                ('^autowriter\.backup_projects_default_params_20261030$'),
                ('^(truth_vault|autowriter)\.backup_[a-z_]+_d129(_twins)?_20261026$'),
                ('^(truth_vault|autowriter)\.backup_([a-z_]+_)?d129p3(_[a-z]+)?_20261027$'),
                ('^(truth_vault|autowriter)\.backup_([a-z_]+_)?i25(_ids)?_20261027$'),
                ('^autowriter\._bak_1102_dup_[a-z_]+$'),
                ('^autowriter\._bak_1102_novelty_rules$'),
                ('^autowriter\._bak_1103_(spx_rules|tuge_comment_rules)$'),
                ('^autowriter\._bak_1110_tuge_(comment_rules|default_params)$'),
                ('^autowriter\._bak_1111_tuge_(comment_rules|rule_compiles)$'),
                ('^autowriter\._bak_1113_ending_rule$'),
                ('^autowriter\._bak_1123_ending_rule_compile$'),
                ('^truth_vault\.backup_external_publish_time_j17_20261125$'),
                ('^truth_vault\.backup_repoint_stale_(comments|comment_judge)_20261125$'),
                ('^truth_vault\.backup_repoint_stale_ssll_(samples|marks)_20261125$')
        )
        SELECT COUNT(*)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname IN ('truth_vault', 'autowriter', 'public')
          AND c.relname ~ '(backup|^_bak_[0-9]{4}_|_20[0-9]{6}$)'
          AND (n.nspname, c.relname) <> ('truth_vault', 'backup_d129_ids_20261026')
          AND NOT EXISTS (SELECT 1 FROM registered r WHERE n.nspname || '.' || c.relname ~ r.pat)$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 有新备份没登记 (D-136: 留着, 不要删)。在 docs/backup-registry.md 和这里的 VALUES 各加一条同样的规则 '
    '(CI 守卫 check_verify_backup_registry.py 要两边一致)。11-25 生产 82 张备份表全部登记, 读数 0。'

UNION ALL
SELECT '93', 'I · 数据一致性',
    'v_notes_vanished 行数: 盖过 last_seen 戳、但本项目最近一次完整同步没见到的篇 (飞书里删了; 审计 B-21 / D-103)',
    COALESCE(pg_temp.safe_count($q$SELECT COUNT(*) FROM truth_vault.v_notes_vanished$q$)::TEXT, 'N/A'),
    '0',
    '> 0 = 飞书里删了但 TV 还留着 (10-09 实查 HATHERINE 6 · TUGE 4, 全已标 essence、0 在 ssll、0 有经验卡). 新策展 / 通道 1 推送 / 闸二取数 10-09 起自动排除; 11-15 起 (D-154 第 8 条) 缺席满 36 小时的: 馆员不再借它的经验卡, 已推去 ssll 的样本每晚自动撤几篇 (一轮最多 5 篇); note 本身不删, 删不删还是 owner 定.'

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

UNION ALL
SELECT '95', 'H · 跨 schema 孤儿',
    'public.reference_samples (三省六部样本) 的 source_truth_vault_note_id 在 truth_vault.notes 里已经没有的行数 (D-129 / L-10)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM public.reference_samples r
        LEFT JOIN truth_vault.notes n ON n.note_id = r.source_truth_vault_note_id
        WHERE r.source_truth_vault_note_id IS NOT NULL AND n.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 删 TV 笔记之前没撤它推去三省六部的样本. 通道 1 的回收 (D-087 B 路) 找不到 TV 行只记 missing、不撤, 这些样本会一直留在高权重参考池里. '
    '修法同 D-129: 先备份这些样本行 (存 truth_vault, 别存 public), 再按 id 删; 没有 TV 来源的原生样本 (列为空) 不算.'

UNION ALL
SELECT '96', 'H · 跨 schema 孤儿',
    'truth_vault.content_scores (闸三分) 指向不存在的笔记的行数 (表对 notes 没有外键; D-129 / L-10)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.content_scores s
        LEFT JOIN truth_vault.notes n ON n.note_id = s.subject_id
        WHERE s.subject_type = 'note' AND n.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 删笔记那一步漏了闸三分. 修法同 D-129: 先 CREATE TABLE truth_vault.backup_content_scores_<原因>_<日期> AS SELECT 这些行 (闸三冻结集要可复现), 再按 subject_id 删.'

UNION ALL
SELECT '97', 'H · 跨 schema 孤儿',
    'autowriter.tv_edit_diffs (改稿差异) 指向不存在的 TV 笔记的行数 (跨 schema 没有外键, #94 只盖对照表; D-129 / L-10)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM autowriter.tv_edit_diffs e
        LEFT JOIN truth_vault.notes n ON n.note_id = e.note_id
        WHERE n.note_id IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 删笔记时没清 aw 的改稿差异, 这些行还会进写作台的改稿摘要. 修法同 D-129: 先 CREATE TABLE autowriter.backup_tv_edit_diffs_<原因>_<日期> AS SELECT 这些行, 再 DELETE.'

UNION ALL
SELECT '98', 'B · truth_vault',
    '投流证据链 v1_22 (D-133) 缺几个对象: 5 个视图 (v_paid_marker_elements / v_paid_boost_events / v_paid_boost_quarantine / '
    'v_paid_boost_readings / v_paid_boost_evidence) + 6 个函数 (tv_safe_date / tv_raw_cell / tv_cell_elements / tv_pyrepr_elements / '
    'tv_classify_paid_element / tv_parse_ops_date)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT 11
            - (SELECT COUNT(*) FROM pg_views WHERE schemaname = 'truth_vault'
                 AND viewname IN ('v_paid_marker_elements', 'v_paid_boost_events', 'v_paid_boost_quarantine',
                                  'v_paid_boost_readings', 'v_paid_boost_evidence'))
            - (SELECT COUNT(DISTINCT p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'truth_vault'
                  AND p.proname IN ('tv_safe_date', 'tv_raw_cell', 'tv_cell_elements', 'tv_pyrepr_elements',
                                    'tv_classify_paid_element', 'tv_parse_ops_date'))$q$
    )::TEXT, 'N/A'),
    '0',
    '11 = schemas/notes_v1_22_paid_boost_evidence.sql 还没在生产跑 (owner 在 SQL editor 跑, 只建函数和视图, 可重跑); 1–10 = 跑了一半或被人删了, 整份重跑.'

UNION ALL
SELECT '99', 'I · 数据一致性',
    'data_quality_flags.paid_promoted = true、却既不在 v_paid_boost_events 也不在 v_paid_boost_quarantine 的篇数 (D-133: 打了投流标记的每一篇都要有去处)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes n
        WHERE n.data_quality_flags -> 'paid_promoted' = 'true'::jsonb
          AND n.note_id NOT IN (SELECT note_id FROM truth_vault.v_paid_boost_events)
          AND n.note_id NOT IN (SELECT note_id FROM truth_vault.v_paid_boost_quarantine)$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = sync 的判据 (_common.classify_paid_element) 和 v1_22 的 SQL 判据漂开了, 或者 paid_promoted 是旧判据留下的、这篇今晚还没重算 '
    '(data_quality_flags 受 UPSERT 保护). 先看 v_paid_marker_elements 里这篇的行; CI check_paid_boost.py 的 parity 段本该挡住前一种.'

UNION ALL
SELECT '100', 'I · 数据一致性',
    '投流标记要人看的两类 (认不出的标记元素数 / 投流标记被删的篇数): 前者 = v_paid_marker_elements 里 marker_like_unrecognized '
    '(准备投流、不投流、整串「关注后续流量 爆贴」…); 后者 = audit_log 里 paid_promoted 从 true 变成非 true 的篇 (标记从飞书删了, 事件也跟着从视图里消失)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.v_paid_marker_elements WHERE class = 'marker_like_unrecognized'$q$
    )::TEXT, 'N/A') || '/' ||
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(DISTINCT a.row_id) FROM truth_vault.audit_log a
        WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
          AND a.changed_cols ? 'data_quality_flags'
          AND a.changed_cols -> 'data_quality_flags' -> 0 -> 'paid_promoted' = 'true'::jsonb
          AND COALESCE(a.changed_cols -> 'data_quality_flags' -> 1 -> 'paid_promoted', 'null'::jsonb) <> 'true'::jsonb$q$
    )::TEXT, 'N/A'),
    '0/0',
    '前一个数 > 0 = 运营用了一种认不出的写法, 那几行在 v_paid_boost_quarantine 里 (reason = marker_like_unrecognized), 问运营是什么意思 (O-06), '
    '要认就两边一起改 _common.PAID_* 和 v1_22 的 tv_classify_paid_element; 后一个数 > 0 = 有投流标记被删过, 按 audit_log 那一行找回原值, '
    '问运营是标错了还是删错了 (10-29 生产 0 篇; 这条是全表扫 audit_log, 约 0.4 秒).'

-- ── v1_23 正文指纹 (外部审计 11-02 F02 第一期, D-137) ─────────────────────
UNION ALL
SELECT '101', 'I · 数据一致性',
    '已标 essence、却没有 essence_content_sha 的篇数 (v1_23 回填之后应为 0; 之后每次标 essence 都写这一列)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes
        WHERE essence_annotated_at IS NOT NULL AND essence_content_sha IS NULL$q$
    )::TEXT, 'N/A'),
    '0',
    'N/A = schemas/notes_v1_23_content_sha.sql 还没跑 (owner 在 SQL editor 跑; 没跑之前代码照旧只标没标过的). '
    '> 0 = 回填漏了, 或者有别的路径标 essence 时没写指纹 (只有 annotate_essence_pass.write_essence_back 该写 essence): '
    '这些篇在夜跑里会被当成过期重标一次, 不丢数据, 但要查是哪条路径.'

UNION ALL
SELECT '102', 'I · 数据一致性',
    'essence 过期的篇数: 已标 essence、但标的时候那份正文和现在不是一份 (essence_content_sha IS DISTINCT FROM content_sha; 只改空白 / 标点 / #话题 不算)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.notes
        WHERE essence_annotated_at IS NOT NULL AND essence_content_sha IS DISTINCT FROM content_sha$q$
    )::TEXT, 'N/A'),
    '0',
    '跑完 v1_23 当天是几百 (11-02 预演 508: OKMAN 318 / TUGE 65 / XIWU_phase2 54 / SPX 29 / HATHERINE 26 …), 不是全库 6838 —— '
    '接近已标总数 = 回填没对上, 回来查. 之后夜跑 essence 在 WORKER_LIMIT 日预算里先标没标过的、再消这些, 应逐日下降, '
    '平时只剩当天飞书里改过的几篇; 连续一周不降 = 夜跑没在消 (看 daily-sync essence 步的 Found 行 content_changed=N). '
    'on_demand 项目夜跑不标, 它们的过期篇留着, 要消就手动跑 backfill-essence.'

UNION ALL
SELECT '103', 'I · 数据一致性',
    '书架上 essence 比卡新的经验卡数 (v_flywheel_lesson_cards 里已策展、notes.essence_annotated_at > curated_at)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.v_flywheel_lesson_cards v
        JOIN truth_vault.notes n ON n.note_id = v.source_note_id
        WHERE v.is_curated AND n.essence_annotated_at > v.curated_at$q$
    )::TEXT, 'N/A'),
    '0',
    'D-137 起夜跑策展分两遍: 先每个项目策展没策展过的卡, 预算有剩再每个项目重策展这些 (同 --recurate-stale 的判据; v1_23 跑过才重策展, '
    '没跑之前夜跑不碰它们, 和以前一样). essence 因正文改过重标之后这里会先涨、'
    '再被夜跑消掉 (11-02: 正文改过的篇上有卡 42 张, OKMAN 33). 一周不降 = 夜跑策展预算被新卡占满, 手动跑 recurate-lessons.yml (stale).'

UNION ALL
SELECT '104', 'H · 跨 schema 孤儿',
    'aw 判稿记成 ok、账本却一行都没有的稿件版本数 (batch_metrics meta.judge 里 status=ok 的 version_id, 在 note_feature_answers 里 aw_version × primary 0 行; #87 的盲区: 它只看已有行的 subject)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM (
            SELECT DISTINCT e->>'version_id' AS version_id
            FROM autowriter.batch_metrics m,
                 jsonb_array_elements(CASE WHEN jsonb_typeof(m.meta->'judge') = 'array'
                                           THEN m.meta->'judge' ELSE '[]'::jsonb END) e
            WHERE m.meta->>'mode' = 'deskcore_commit'
              AND e->>'status' = 'ok' AND e->>'version_id' IS NOT NULL
        ) j
        WHERE NOT EXISTS (SELECT 1 FROM truth_vault.note_feature_answers a
                          WHERE a.subject_type = 'aw_version' AND a.subject_id = j.version_id
                            AND a.run_tag = 'primary')$q$
    )::TEXT, 'N/A'),
    '0',
    '外部评审 11-04 F04: Jev /judge_draft 判成功、写账本失败时回 200 + written=0 + write_error, aw 照样记 judge_status=ok, 不报警. '
    '分母取 batch_metrics (aw 记的每次判稿), 不取账本已有行, 所以「一行都没写进去」的也数得到. 11-04 生产 338 个 ok 版本、0 个没账本. '
    '> 0 = 这些版本的账本缺了: aw 拿不到待写行, 只能按 version_id 重判一次 (约 1 次 Jev 调用一篇); 记判稿超时 (timeout) 的不算在这里 (deskcore.md 认的缺口).'

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

-- ── 2026-11-25 batch 1 (S-02 / S-09) 追加的行 ─────────────────────────────
UNION ALL
SELECT '92b', 'I · 数据一致性',
    '客户端角色 (anon / authenticated) 有任何权限的「备份表 × 角色」数 (一张表两个角色都能碰算 2; 名字规则同 #92; S-02)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES ('anon'), ('authenticated')) r(role)
        WHERE c.relkind = 'r' AND n.nspname IN ('truth_vault', 'autowriter', 'public')
          AND c.relname ~ '(backup|^_bak_[0-9]{4}_|_20[0-9]{6}$)'
          AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.role)
          AND has_table_privilege(r.role, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 有备份表能被看板 / 公网的 key 读写 (备份里有正文和评论)。11-25 生产 0: 有 16 张备份没开 RLS, 但都没有授权, '
    'truth_vault 也不给 anon 用, 所以不用补开 RLS。真 > 0 时: REVOKE ALL ON <表> FROM anon, authenticated。'

UNION ALL
SELECT '105', 'J · 看板与权限',
    'public 下 v_dash_* 看板视图的个数 (Step 0b 的 dashboard_views_v1–v6 都跑过; S-09 / 审计 C-16)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'v' AND c.relname LIKE 'v\_dash\_%'$q$
    )::TEXT, 'N/A'),
    '18',
    '11-25 生产 18 个。少了 = scripts/README.md Step 0b 里有一份看板视图没跑, 按 Step 0b 的顺序补跑; '
    '多了 = 有人加了视图没写进 schemas/, 或者 CI 的探针视图 v_dash_probe 跑进了生产 (那就删掉它)。'

UNION ALL
SELECT '106', 'J · 看板与权限',
    'anon 在 public 下还有写权限 (INSERT / UPDATE / DELETE / TRUNCATE) 的「表或视图 × 权限」数 (S-09)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) p(priv)
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p')
          AND has_table_privilege('anon', c.oid, p.priv)$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 拿着看板那把公开 key 的人能改这些表 / 视图。跑 schemas/security_revoke_anon_write_public_tables.sql 和 '
    'security_revoke_anon_write_dash_views.sql (Step 0b; 都能重跑)。11-25 生产 0。'

UNION ALL
SELECT '107', 'J · 看板与权限',
    'public 下三省六部的 5 张表里没开 RLS 的张数 (projects / pipeline_runs / stage_logs / outputs / reference_samples; D-101)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
          AND c.relname IN ('projects', 'pipeline_runs', 'stage_logs', 'outputs', 'reference_samples')$q$
    )::TEXT, 'N/A'),
    '0',
    '> 0 = 匿名 key 能整表读三省六部的正文和评论。跑 schemas/security_rls_public_ssll_tables.sql (Step 0b; 能重跑)。11-25 生产 0。'

UNION ALL
SELECT '108', 'I · 数据一致性',
    '闸三的分: 第一条带 input_sha 的分之后, 又写进来的 input_sha 为空的行数 (v1_29; AU-F02b ②)',
    COALESCE(pg_temp.safe_count(
        $q$SELECT COUNT(*) FROM truth_vault.content_scores s
        WHERE s.input_sha IS NULL
          AND s.scored_at > (SELECT min(scored_at) FROM truth_vault.content_scores WHERE input_sha IS NOT NULL)$q$
    )::TEXT, 'N/A'),
    '0',
    'N/A = schemas/notes_v1_29_content_scores_input_sha.sql 还没跑 (gate3_score.py 照旧打分, 只是不记)。'
    '跑之前的分都是空的, 不算 (不回填)。> 0 = 有一条写分的路没带 input_sha, 或者那篇的 essence_content_sha 是空的 (对照 #101)。'

UNION ALL
SELECT '109', 'I · 数据一致性',
    '整条改指到另一篇帖的笔记上, 还挂着的旧帖运营评论行数 (改指之前入库、正文在现在的随贴评论里找不到, '
    '且这篇还有随贴评论原文或改指时换了发布时间; 链接只差空白不算改指; AU-F02b ④ / D-173)',
    COALESCE(pg_temp.safe_count(
        $q$WITH rp AS (
            SELECT a.row_id AS note_id, max(a.occurred_at) AS last_rp, bool_or(a.changed_cols ? 'publish_time') AS pt_changed
            FROM truth_vault.audit_log a
            WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
              AND a.changed_cols ? 'publish_url' AND a.changed_cols ? 'account_id'
              AND btrim(coalesce(a.changed_cols->'publish_url'->>0, ''), E' \t\r\n') <> ''
              AND btrim(coalesce(a.changed_cols->'publish_url'->>1, ''), E' \t\r\n') <> ''
              AND btrim(a.changed_cols->'publish_url'->>0, E' \t\r\n') IS DISTINCT FROM btrim(a.changed_cols->'publish_url'->>1, E' \t\r\n')
            GROUP BY a.row_id
        )
        SELECT COUNT(*) FROM rp JOIN truth_vault.notes n ON n.note_id = rp.note_id
        JOIN truth_vault.comments c ON c.note_id = rp.note_id
        WHERE c.source IS NULL AND c.created_at < rp.last_rp
          AND (n.raw_extra ? '_comment_text' OR n.raw_extra ? '_comment_text_persona' OR rp.pt_changed)
          AND position(btrim(c.content) IN coalesce(n.raw_extra->>'_comment_text', '') || E'\n'
                                           || coalesce(n.raw_extra->>'_comment_text_persona', '')) = 0$q$
    )::TEXT, 'N/A'),
    '0',
    '11-25 生产 765 (全在 OKMAN_phase1, 242 篇), 都有 Jev 的评论判分。这一行按 D-173 的提议数: 要改 D-119 #15, 要 owner 点头; '
    '11-25 问了还没答, 没答之前 765 是已知的, 不用清。owner 同意删之后的清法: 先跑 '
    'scripts/cleanup_repointed_stale_comments_au_f02b.sql (先备份、再删评论和判分, 能重跑), 同意撤样本的话再跑 withdraw (见 #110)。'
    'owner 不同意删的话, 把期望改成当时的读数。没有原文键、改指时也没换发布时间的篇上另有 16 条 (OKMAN 13、TUGE 3), '
    '「找不到」只说明源清空了, 不算进这一行, 照 D-119 #15 留着 (D-173 第 3 条)。'

UNION ALL
SELECT '110', 'H · 跨 schema 孤儿',
    '三省六部里旧帖内容、挂着改指后 note_id 的通道 1 样本数 (改指之前推的、样本正文和现在的正文不一样; 改指认法同 #109; AU-F02b ④)',
    COALESCE(pg_temp.safe_count(
        $q$WITH rp AS (
            SELECT a.row_id AS note_id, max(a.occurred_at) AS last_rp, bool_or(a.changed_cols ? 'publish_time') AS pt_changed
            FROM truth_vault.audit_log a
            WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
              AND a.changed_cols ? 'publish_url' AND a.changed_cols ? 'account_id'
              AND btrim(coalesce(a.changed_cols->'publish_url'->>0, ''), E' \t\r\n') <> ''
              AND btrim(coalesce(a.changed_cols->'publish_url'->>1, ''), E' \t\r\n') <> ''
              AND btrim(a.changed_cols->'publish_url'->>0, E' \t\r\n') IS DISTINCT FROM btrim(a.changed_cols->'publish_url'->>1, E' \t\r\n')
            GROUP BY a.row_id
        )
        SELECT COUNT(*) FROM rp JOIN truth_vault.notes n ON n.note_id = rp.note_id
        JOIN public.reference_samples r ON r.source_truth_vault_note_id = rp.note_id
        WHERE r.created_at < (rp.last_rp AT TIME ZONE 'UTC') AND r.post_body IS DISTINCT FROM n.raw_content$q$
    )::TEXT, 'N/A'),
    '0',
    '11-25 生产 29 (全在 OKMAN_phase1)。会动外部下游, 要 owner 先看: scripts/withdraw_repointed_stale_ssll_samples_au_f02b.sql '
    '(先清标记、再删样本, 下一晚通道 1 按现在的帖重推仍是爆 / 大爆的; 能重跑)。它要求 #109 先清到 0; '
    'owner 定了不删旧帖评论或不撤的话, 把期望改成当时的读数。'

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
ORDER BY length(ord), ord;   -- 编号到了三位 (#100), 按文本排会插到 '03' 和 '11' 中间
