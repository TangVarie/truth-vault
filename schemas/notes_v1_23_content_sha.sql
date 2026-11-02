-- truth_vault v1.23 · 内容指纹: notes.content_sha + notes.essence_content_sha (外部审计 11-02 F02 第一期, D-137, 2026-11-02)
-- ════════════════════════════════════════════════════════════════════
-- 治的是什么:
--   飞书里的正文改了, sync 把 raw_content 覆盖掉, 但 essence / 经验卡 / 闸三分数都还是按改之前那份标的 —— 没有任何东西
--   知道"这篇的正文变过"。essence 按 essence_annotated_at IS NULL 取, 标过一次就再也不看; 夜跑策展只取没策展过的卡。
--   11-02 生产只读 (audit_log, 只数不读正文): 6835 篇已标 essence 里, 571 篇的 raw_content 在 essence 之后改过 (近 14 天 135 篇),
--   按下面的规则去掉空白 / 标点 / #话题 之后还不一样的 508 篇 (OKMAN_phase1 318、TUGE_phase1 65、XIWU_phase2 54、
--   SPX_phase1 29、HATHERINE_phase1 26 …); 书架上有卡的 42 张 (OKMAN 33)。两种来路: OKMAN 那 318 篇是 07-27～08-18 整条
--   record 改指到另一篇帖 —— audit_log 里同一行 UPDATE 连 publish_url (新旧都不为空)、账号、发布时间、指标、tier 一起换
--   (319/319), 现在的行自己是对的, 只有旧 essence 是按别的帖标的; 其余约 190 篇是排期稿进了飞书之后、发出去之前又改过
--   (publish_url 是新填上的)。
--
-- 这份迁移做三件事:
--   ① truth_vault.tv_content_sha(title, raw_content): 标题 + 换行 + 正文, 去掉「[话题]」、#话题 (# 后最多 40 个不是空白、# 或方括号的字符)、
--      全部空白和标点, 再取 md5。只改空格 / 换行 / 标点 / 话题标签不算改 —— 不然夜跑每次同步都会让一批篇白白重标。
--      Python 同一份在 scripts/_common.py content_sha() (CI sql job 拿同一批字符串两边对; 两个字符类里 ASCII 以外的字符
--      两边都写成 \uXXXX, 文件里没有看不见的字符; 不依赖库的 locale)。
--   ② notes.content_sha: 上面那个函数的 STORED 生成列, 正文一改它就跟着变, 不用任何代码去写。
--      notes.essence_content_sha: essence 标的时候那份正文的指纹 —— annotate_essence_pass.write_essence_back 每次标都写。
--      essence_annotated_at 不为空、两个指纹不一样 = 这篇的 essence 是按旧正文标的 (过期), 夜跑 essence 在同一份日预算里
--      先标没标过的、再重标过期的; essence 重标之后 essence_annotated_at 比卡新, 夜跑策展先策展没策展过的卡、再重策展这些。
--   ③ 一次性回填 essence_content_sha: 用 audit_log 还原 essence 标注那一刻的标题和正文 (essence_annotated_at 之后第一次改
--      raw_content / title 的那一行的旧值; 之后没改过的就是现在的值), 算指纹写进去。所以只有 essence 之后正文真改过的篇
--      变成过期, 不是全库 6838 篇一起重标。
--
-- 挡不住什么 / 不做什么:
--   · 闸三不重打分 (D-118 入库即打分)。分数按旧正文标的 essence 打的那些, 出读数时按 D-137 预先登记的敏感性切片单列。
--   · 特征层 (note_feature_answers) 不跟着重抽、content_scores 不加 input_sha —— 都是第二期 (OPEN-ITEMS AU-F02b), 这份迁移
--     不碰。OKMAN 那 318 篇的指标和 tier 已经跟着帖一起换过了 (audit_log 同一行), 不用另修。
--   · 飞书里改的只是 hashtags 列 / 评论区 / 指标: 不算正文改动, 不重标。
--   · 生成列只在这份迁移跑的那一刻按函数当时的定义算; 以后要改规则 = 新迁移: 改函数 + 重建这一列 + 重算 essence_content_sha,
--     不能只 CREATE OR REPLACE 函数 (存量的值不会跟着变)。
--
-- 代码是宽容的: 这两列没建之前, 夜跑 essence / 计数 / 写回照今天的行为走, 只打一行 warning (scripts/_common.py
--   notes_content_sha_supported); 不把这两列收进 _REQUIRED_COLUMNS, 免得迁移没跑之前 sync 先红。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次 (或 MCP apply_migration, 文件与 main 一字不差)。可以重跑: 函数 CREATE OR
--   REPLACE、两列 IF NOT EXISTS、回填只碰 essence_content_sha 还是空的已标篇。加生成列会把 notes 整表重写一遍 (6838 行,
--   几秒, 期间锁表), 别和 daily-sync 撞 (daily-sync 实际 08:00–09:30 UTC 跑)。
--   回填那一段临时关掉 notes 上的审计触发器和 updated_at 触发器 (同一个事务里关、写、开, 中途出错整段回滚、触发器不会停在关着):
--   6835 行只写一个派生列, 不该往 audit_log 灌 6835 行噪声, 也不该把每篇的 updated_at 都改成今天。
-- 跑完看最后那行 SELECT (预期: 已标 6835 左右、回填 6835 左右、过期几百 —— 11-02 预演是 508; 如果过期接近已标总数,
--   说明回填没对上, 先别等夜跑, 回来查), 再跑 scripts/verify_supabase_state.sql 的 #101 / #102。
-- 在 notes_v1_2 (notes / audit_log / 两个触发器) 之后应用。
-- ════════════════════════════════════════════════════════════════════


-- ── ① 指纹函数 ─────────────────────────────────────────────────────
--   三步, 顺序不能换: 先去「[话题]」(把 #词[话题]# 变成 #词#), 再去 #话题 (# 后面最多 40 个非空白、非 #、非方括号的字符,
--   同 feature_bank._HASHTAG_BARE), 最后去全部空白和标点 (剩下的孤零零的 # 也在这一步去掉)。
--   字符类里 ASCII 以外的字符全写成 \uXXXX (Postgres ARE 和 Python re 都认): 文件里没有零宽 / 不换行 / 行分隔这类看不见的
--   字符, 粘贴进 SQL editor 不会被编辑器吞掉或换掉 —— 吞掉一个端点会悄悄改掉一段范围, 两边仍各自自洽, CI 看不出来。
--   结果不随库的 locale 变 (11-02 在生产 17.6 / en_US.UTF-8 和 CI 16 / C.UTF-8 上对过同一批字符串; 改成 \uXXXX 前后,
--   PG 16 和 Python 对全部 1,112,063 个码位逐个比过, 两个字符类的归属一个不差)。去掉的标点: ASCII 标点和控制符、Latin-1 标点 (U+00A1–U+00BF)、
--   U+2000–U+206F (各种空格、零宽字符、破折号、引号、省略号)、CJK 标点 (U+3000–U+3004, U+3008–U+3020, U+3030, U+303D–U+303F;
--   〇 々 这类算字, 留着)、变体选择符和竖排 / 小写形式 (U+FE00–U+FE19, U+FE30–U+FE6B)、BOM、全角标点 (U+FF01–U+FF0F,
--   U+FF1A–U+FF20, U+FF3B–U+FF40, U+FF5B–U+FF65)。字母、数字、汉字、表情都留着: 换一个表情算改了。
CREATE OR REPLACE FUNCTION truth_vault.tv_content_sha(title text, raw_content text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path = ''
AS $fn$
    SELECT md5(
        regexp_replace(
            regexp_replace(
                regexp_replace(coalesce(title, '') || E'\n' || coalesce(raw_content, ''),
                               '\[话题\]', '', 'g'),
                '#[^#\[\]\u0001- \u007f-\u00a0\u1680\u2000-\u200b\u2028\u2029\u202f\u205f\u3000\ufeff]{1,40}', '', 'g'),
            '[\u0001-/:-@[-`{-\u00bf\u1680\u2000-\u206f\u3000-\u3004\u3008-\u3020\u3030\u303d-\u303f\ufe00-\ufe19\ufe30-\ufe6b\ufeff\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65]',
            '', 'g'));
$fn$;

COMMENT ON FUNCTION truth_vault.tv_content_sha(text, text) IS
    '正文指纹 (D-137 / 审计 11-02 F02): md5(标题 + 正文, 去 [话题] / #话题 / 空白 / 标点)。Python 同一份: scripts/_common.py content_sha()。'
    '改规则要新迁移重建 notes.content_sha 并重算 essence_content_sha, 不能只替换函数。';


-- ── ② 两列 ─────────────────────────────────────────────────────────
ALTER TABLE truth_vault.notes
    ADD COLUMN IF NOT EXISTS content_sha TEXT
    GENERATED ALWAYS AS (truth_vault.tv_content_sha(title, raw_content)) STORED;

ALTER TABLE truth_vault.notes
    ADD COLUMN IF NOT EXISTS essence_content_sha TEXT;

COMMENT ON COLUMN truth_vault.notes.content_sha IS
    '现在这份标题 + 正文的指纹 (生成列, truth_vault.tv_content_sha)。只改空白 / 标点 / #话题 不变 (D-137)。';
COMMENT ON COLUMN truth_vault.notes.essence_content_sha IS
    'essence 标的时候那份正文的指纹 (write_essence_back 写; v1_23 从 audit_log 回填)。essence_annotated_at 非空且与 content_sha 不同 = essence 过期, 夜跑重标 (D-137)。';


-- ── ③ 一次性回填 ───────────────────────────────────────────────────
--   只碰「已标 essence、essence_content_sha 还是空」的篇: 重跑是 0 行; 代码写过的 (v1_23 之后标的) 不会被这里覆盖。
--   essence 标注那一刻的标题 / 正文 = essence_annotated_at 之后第一次改这一列的 UPDATE 行的旧值 (changed_cols -> 列 -> 0);
--   之后没改过 = 现在的值。旧值是 JSON null (那时这一列为空) 也照实算, 所以用「有没有那一行」区分, 不用 coalesce。
--   essence_annotated_at 和 audit_log.occurred_at 都是不带时区的 UTC (_common._iso_now / 库的 now())。
DO $backfill$
BEGIN
    ALTER TABLE truth_vault.notes DISABLE TRIGGER tv_audit_notes;
    ALTER TABLE truth_vault.notes DISABLE TRIGGER tv_notes_updated_at;

    WITH src AS (
        SELECT n.note_id,
               (SELECT a.changed_cols -> 'raw_content'
                  FROM truth_vault.audit_log a
                 WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.row_id = n.note_id
                   AND a.operation = 'UPDATE' AND a.changed_cols ? 'raw_content'
                   AND a.occurred_at > n.essence_annotated_at
                 ORDER BY a.occurred_at, a.audit_id
                 LIMIT 1) AS raw_pair,
               (SELECT a.changed_cols -> 'title'
                  FROM truth_vault.audit_log a
                 WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.row_id = n.note_id
                   AND a.operation = 'UPDATE' AND a.changed_cols ? 'title'
                   AND a.occurred_at > n.essence_annotated_at
                 ORDER BY a.occurred_at, a.audit_id
                 LIMIT 1) AS title_pair
          FROM truth_vault.notes n
         WHERE n.essence_annotated_at IS NOT NULL
           AND n.essence_content_sha IS NULL
    )
    UPDATE truth_vault.notes n
       SET essence_content_sha = truth_vault.tv_content_sha(
               CASE WHEN s.title_pair IS NULL THEN n.title ELSE s.title_pair ->> 0 END,
               CASE WHEN s.raw_pair IS NULL THEN n.raw_content ELSE s.raw_pair ->> 0 END)
      FROM src s
     WHERE s.note_id = n.note_id;

    ALTER TABLE truth_vault.notes ENABLE TRIGGER tv_notes_updated_at;
    ALTER TABLE truth_vault.notes ENABLE TRIGGER tv_audit_notes;
END
$backfill$;


-- ── 跑完看这一行 ───────────────────────────────────────────────────
--   已标 ≈ 回填 (6835 左右); 过期 = 几百 (11-02 预演 508, 每晚 essence 在日预算里先标没标过的、再一点点消掉它)。
--   过期接近已标总数 = 回填没对上 (比如函数和预演时不是一份), 先别等夜跑, 回来查。
SELECT count(*)                                                        AS notes_total,
       count(*) FILTER (WHERE essence_annotated_at IS NOT NULL)        AS essence_annotated,
       count(*) FILTER (WHERE essence_content_sha IS NOT NULL)         AS essence_sha_filled,
       count(*) FILTER (WHERE essence_annotated_at IS NOT NULL
                          AND essence_content_sha IS DISTINCT FROM content_sha) AS essence_stale
  FROM truth_vault.notes;
