-- truth_vault v1.28 · 首图特征: 每篇一行的状态、题库名单的镜像、三个函数、两张视图 (I-29, D-158, 2026-11-16)
-- ════════════════════════════════════════════════════════════════════
-- 这份迁移全是加法, 不改任何已有的表、列、视图、函数:
--   ① 表 truth_vault.note_first_image        每篇帖一行: 读的是哪一列、第一个附件的指纹、几个附件、结果是什么、试了几次、
--                                              下次什么时候再试。图片本身不存, file_token 也不再存一份 (只存它的 sha256)。
--   ② 表 truth_vault.first_image_bank_state   只有一行: 题库文件 (prompts/first_image_questions_v0_2.yaml) 里三张名单的镜像 ——
--                                              确认过封面的项目、先不做的项目、往外给的题。首图步骤每晚开头照题库文件写一遍。
--   ③ 视图 truth_vault.v_note_first_image_source  哪一列、哪个附件算首图 (内容配图 > 笔记配图 > 图片, 取第 0 个)。规则只写在这里。
--   ④ 函数 first_image_candidates             这一晚该做哪些帖: 经验卡背后的帖 + 某天之后入库的新帖 (入库时发布还不到 30 天; 整张表
--                                              刚接进来或删了重灌时带进来的老帖不算); 有首图、没做过或图换了或到了重试时间;
--                                              先不做的项目和飞书里已删的帖不出。
--   ⑤ 函数 write_first_image_result           一张图的结果一次写完 (同一个事务): 先删这篇旧的首图答案, 再写新的答案和状态。
--   ⑥ 函数 sync_first_image_bank              写 ② 那一行。
--   ⑦ 视图 truth_vault.v_first_image_features  给下游读的那一面: 每篇做过的帖一行, 带状态、标记和【能用的】答案。
--                                              不能用的 (不是封面 / 多图且没人确认 / 项目先不做 / 没答成 / 做完之后首图换了或没了)
--                                              answers 是 NULL。几个附件、首图换没换, 都是读的那一刻按帖子现在的图片列算的。
--
-- 答案存在哪: 还是 truth_vault.note_feature_answers (v1.13), run_tag = 'img-primary', 题号以 img_ 开头,
--   extractor = 'llm:<模型名>' (模型答的) 或 'code:fi' (代码算的两道)。文字题库的视图只读 run_tag = 'primary', 碰不到这些行。
--   封面上抄下来的那句大字 (img_main_text) 也存在这张表里 (设计 §5.6: 和帖子正文一样留在库里), 但 ⑦ 不往外给。
--
-- 谁能读写: 两张表开了行级安全、没有策略; 表、视图、函数都只给 service_role, anon / authenticated 一概没有。
--
-- 没跑这份 SQL 之前: 首图步骤 (scripts/first_image_pass.py) 发现函数不在, 打一行说明就结束, 不下载、不调模型、不花钱,
--   别的夜跑不受影响。跑了之后, 下一晚的首图步骤开始做 (每晚有图片数和 token 两道上限, 见 docs/34-first-image-pass.md)。
--   所以这份 SQL 就是开关: 先合代码还是先跑它都可以。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次。可以重跑 (表 IF NOT EXISTS, 函数和视图 CREATE OR REPLACE, 权限和注释覆盖写),
--   重跑不动已有的行。要在 v1.4 (经验卡视图)、v1.13 (答案表)、v1.21 / v1.25 (飞书已删的帖) 之后。
-- 回滚: DROP VIEW truth_vault.v_first_image_features, truth_vault.v_note_first_image_source;
--        DROP FUNCTION truth_vault.first_image_candidates(TEXT,TIMESTAMP,TEXT[],BOOLEAN,INT),
--                      truth_vault.write_first_image_result(JSONB,JSONB),
--                      truth_vault.sync_first_image_bank(TEXT,TEXT,TEXT[],TEXT[],TEXT[]);
--        DROP TABLE truth_vault.note_first_image, truth_vault.first_image_bank_state;
--        DELETE FROM truth_vault.note_feature_answers WHERE run_tag = 'img-primary';   (要不要删答案看情况, 留着不碍事)
-- 夹具与反证: scripts/check_first_image_pg.py (ci.yml sql job, 真 Postgres); 步骤那一半的守卫是 scripts/check_first_image_pass.py。
-- ════════════════════════════════════════════════════════════════════
BEGIN;

-- ── ① 每篇一行的状态 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.note_first_image (
    note_id        TEXT PRIMARY KEY REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    project_id     TEXT NOT NULL,
    source_column  TEXT NOT NULL CHECK (source_column IN ('内容配图', '笔记配图', '图片')),
    file_sha       TEXT NOT NULL CHECK (file_sha ~ '^[0-9a-f]{64}$'),
    n_files        INT  NOT NULL CHECK (n_files >= 1),
    file_kind      TEXT NOT NULL CHECK (file_kind IN ('jpeg', 'png', 'heic', 'empty_type', 'video', 'other')),
    file_bytes     BIGINT,
    width          INT,
    height         INT,
    status         TEXT NOT NULL CHECK (status IN ('answered', 'not_a_cover', 'first_is_video', 'too_large', 'decode_failed',
                                                    'download_failed', 'no_answer', 'model_failed')),
    bank_version   TEXT NOT NULL,
    bank_sha256    TEXT NOT NULL,
    model          TEXT,
    attempts       INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    tries          INT NOT NULL DEFAULT 0 CHECK (tries >= 0),
    next_try_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tv_note_first_image_retry
    ON truth_vault.note_first_image (next_try_at) WHERE next_try_at IS NOT NULL;
ALTER TABLE truth_vault.note_first_image ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON truth_vault.note_first_image FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON truth_vault.note_first_image TO service_role;

COMMENT ON TABLE truth_vault.note_first_image IS
    '首图特征的状态, 每篇帖一行 (v1.28)。只由 write_first_image_result 写。图片不存; 答案在 note_feature_answers (run_tag = img-primary); '
    '下游读 v_first_image_features, 不直接读这张表。';
COMMENT ON COLUMN truth_vault.note_first_image.source_column IS '首图取自 raw_extra 的哪一列 (内容配图 / 笔记配图 / 图片)。';
COMMENT ON COLUMN truth_vault.note_first_image.file_sha IS
    '第一个附件的 file_token 的 sha256 (十六进制)。只用来认「这篇是不是为现在这张图做的」: 运营换了图, 指纹变了, 下一晚重做。'
    'file_token 本身不在这里再存一份。';
COMMENT ON COLUMN truth_vault.note_first_image.n_files IS
    '做这一次的时候这一列里有几个附件 (当时的数, 之后运营再加图它不跟着变)。「是不是多图的帖」不看它: v_first_image_features 读的那一刻按帖子现在的图片列数。';
COMMENT ON COLUMN truth_vault.note_first_image.file_kind IS '飞书记的附件类型: jpeg / png / heic / empty_type (类型为空, 看文件名) / video / other。';
COMMENT ON COLUMN truth_vault.note_first_image.width IS '缩图之后的宽 (像素), 模型看到的就是这个大小; 没解开图时是 NULL。';
COMMENT ON COLUMN truth_vault.note_first_image.height IS '缩图之后的高 (像素); 没解开图时是 NULL。';
COMMENT ON COLUMN truth_vault.note_first_image.status IS
    'answered = 模型说是封面, 题答完了; not_a_cover = 模型说不是封面 (后面的题没问, 不上经验卡); first_is_video = 第一个附件是视频 (没下载、没问); '
    'too_large = 超过 48 MiB (没问); decode_failed = 下载到了但解不开 (没问); download_failed = 飞书没给下载; '
    'no_answer = 模型问了但「是不是封面」没答成、或答案自相矛盾整轮作废; model_failed = 模型那边出错 (中转站 / 网络)。'
    '前五种是定下来的结果 (next_try_at 为空); 后三种会重试, 重试用完也是 next_try_at 为空。';
COMMENT ON COLUMN truth_vault.note_first_image.bank_version IS '做这一次用的题库版本 (fi-v0.2)。';
COMMENT ON COLUMN truth_vault.note_first_image.bank_sha256 IS '做这一次时题库文件的校验和。改名单 (确认封面的项目等) 也会让它变, 所以「做没做过」不看它, 看 bank_version。';
COMMENT ON COLUMN truth_vault.note_first_image.model IS '答题的模型名; 没有调过模型 (视频、太大、没下载到、解不开) 是 NULL。';
COMMENT ON COLUMN truth_vault.note_first_image.attempts IS
    '对这张图、这版题库, 算数的失败次数 (飞书明确不给 / 模型答了但不能用)。到 3 次不再自动重试。换了图或换了题库版本从 0 算。';
COMMENT ON COLUMN truth_vault.note_first_image.tries IS
    '对这张图、这版题库一共试了几次, 含不算数的 (网络断、中转站出错)。到 6 次不再自动重试: 防止同一张图每晚白花钱。';
COMMENT ON COLUMN truth_vault.note_first_image.next_try_at IS
    '下次什么时候可以再试; NULL = 不再自动试 (结果定了, 或重试用完了)。失败后约 20 小时, 第二次算数的失败后约 44 小时。';

-- ── ② 题库名单的镜像 (只有一行) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.first_image_bank_state (
    id                       BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
    bank_version             TEXT NOT NULL,
    bank_sha256              TEXT NOT NULL,
    cover_confirmed_projects TEXT[] NOT NULL DEFAULT '{}',
    excluded_projects        TEXT[] NOT NULL DEFAULT '{}',
    surfaced_questions       TEXT[] NOT NULL DEFAULT '{}',
    synced_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE truth_vault.first_image_bank_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON truth_vault.first_image_bank_state FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON truth_vault.first_image_bank_state TO service_role;

COMMENT ON TABLE truth_vault.first_image_bank_state IS
    '题库文件 prompts/first_image_questions_v0_2.yaml 里三张名单的镜像, 只有一行 (v1.28)。首图步骤每晚开头写一遍; 改名单改的是仓里的文件, '
    '不是这张表。这一行还没有 (步骤一次都没跑过) 时, v_first_image_features 里没有一篇算能用。';
COMMENT ON COLUMN truth_vault.first_image_bank_state.cover_confirmed_projects IS
    '有人确认过「多图的帖, 第一个附件就是封面」的项目。不在里面的项目, 多图的帖带 cover_unconfirmed。';
COMMENT ON COLUMN truth_vault.first_image_bank_state.excluded_projects IS '先不做的项目 (今天: RIO / TXQ / WTG)。它们已有的行也不算能用。';
COMMENT ON COLUMN truth_vault.first_image_bank_state.surfaced_questions IS
    '往外给的题 (试跑里两轮对得上的那几道)。别的题的答案也存着, 但 v_first_image_features.answers 里不出。';

-- ── ③ 哪个附件算首图 ─────────────────────────────────────────────────
-- 和 scripts/first_image.py 的 pick_first_image 是同一条规则: 三列里按「内容配图 → 笔记配图 → 图片」的顺序取第一个非空的,
-- 取它的第 0 个附件; 附件 = 数组里带 file_token (非空字符串) 的对象。只看 raw_extra 顶层 (试跑也是这么取的)。
-- 没有首图的帖不出行。
CREATE OR REPLACE VIEW truth_vault.v_note_first_image_source
WITH (security_invoker = true) AS
SELECT n.note_id,
       n.project_id,
       c.source_column,
       c.n_files,
       c.first_file,
       encode(sha256(convert_to(c.first_file ->> 'file_token', 'UTF8')), 'hex') AS file_sha
FROM truth_vault.notes n
CROSS JOIN LATERAL (
    SELECT k.col AS source_column, f.n_files, f.first_file
    FROM (VALUES (1, '内容配图'), (2, '笔记配图'), (3, '图片')) AS k(ord, col)
    CROSS JOIN LATERAL (
        SELECT count(*)::int AS n_files,
               (array_agg(e.elem ORDER BY e.idx))[1] AS first_file
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.raw_extra -> k.col) = 'array'
                                       THEN n.raw_extra -> k.col ELSE '[]'::jsonb END)
             WITH ORDINALITY AS e(elem, idx)
        WHERE jsonb_typeof(e.elem) = 'object'
          AND jsonb_typeof(e.elem -> 'file_token') = 'string'
          AND e.elem ->> 'file_token' <> ''
    ) f
    WHERE f.n_files > 0
    ORDER BY k.ord
    LIMIT 1
) c;
REVOKE ALL ON truth_vault.v_note_first_image_source FROM PUBLIC, anon, authenticated;
GRANT SELECT ON truth_vault.v_note_first_image_source TO service_role;
COMMENT ON VIEW truth_vault.v_note_first_image_source IS
    '哪一列、哪个附件算首图 (v1.28): 内容配图 > 笔记配图 > 图片, 取第 0 个附件。first_file 是飞书的附件对象 (含 file_token), 只给首图步骤下载用; '
    '没有首图的帖不出行。';

-- ── ④ 这一晚该做哪些帖 ───────────────────────────────────────────────
-- 范围 (D-157 / D-158): 经验卡背后的帖 (v_flywheel_lesson_cards.source_note_id), 加上新帖。p_cards_only = true 时只要前一种。老帖不回头补。
-- 新帖 = p_new_since 之后第一次入库 (notes.ingested_at, 之后不变), 并且下面两条占一条:
--   · 有发布时间, 而且入库时发布还不到 30 天;
--   · 还没有发布时间 (运营刚建的行), 而且这个项目在它入库的 7 天之前就已经有帖在库里。
-- 第二个条件是防「整张表刚接进来 / 删了重灌」: 那时候几百篇老帖的 ingested_at 全是当天, 只看入库时刻会把它们全当成新帖
-- 一晚 40 张地补下去。那样的表里, 发布超过 30 天的不做; 没有发布时间的等填上发布时间再看。
-- 要做 = 有首图, 并且 (没做过 / 图换了 / 题库版本换了 / 到了重试时间)。先不做的项目、飞书里已删的帖不出。
-- 顺序: 经验卡的帖在前, 没做过的在前, 新入库的在前。
CREATE OR REPLACE FUNCTION truth_vault.first_image_candidates(
    p_bank_version TEXT, p_new_since TIMESTAMP, p_excluded TEXT[], p_cards_only BOOLEAN, p_limit INT
) RETURNS TABLE (note_id TEXT, project_id TEXT, title TEXT, source_column TEXT, n_files INT,
                 first_file JSONB, file_sha TEXT, is_card BOOLEAN)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT s.note_id, s.project_id, n.title, s.source_column, s.n_files, s.first_file, s.file_sha,
           (c.source_note_id IS NOT NULL) AS is_card
    FROM truth_vault.v_note_first_image_source s
    JOIN truth_vault.notes n ON n.note_id = s.note_id
    LEFT JOIN (SELECT DISTINCT source_note_id FROM truth_vault.v_flywheel_lesson_cards) c
           ON c.source_note_id = s.note_id
    LEFT JOIN truth_vault.note_first_image st ON st.note_id = s.note_id
    WHERE p_bank_version IS NOT NULL
      AND NOT (s.project_id = ANY (coalesce(p_excluded, '{}'::text[])))
      AND NOT EXISTS (SELECT 1 FROM truth_vault.v_notes_vanished v WHERE v.note_id = s.note_id)
      AND (c.source_note_id IS NOT NULL
           OR (NOT coalesce(p_cards_only, false) AND p_new_since IS NOT NULL AND n.ingested_at >= p_new_since
               AND (n.publish_time >= n.ingested_at - interval '30 days'
                    OR (n.publish_time IS NULL
                        AND EXISTS (SELECT 1 FROM truth_vault.notes o
                                    WHERE o.project_id = n.project_id
                                      AND o.ingested_at <= n.ingested_at - interval '7 days')))))
      AND (st.note_id IS NULL
           OR st.file_sha <> s.file_sha
           OR st.bank_version <> p_bank_version
           OR (st.next_try_at IS NOT NULL AND st.next_try_at <= now()))
    ORDER BY (c.source_note_id IS NOT NULL) DESC, (st.note_id IS NULL) DESC, n.ingested_at DESC NULLS LAST, s.note_id
    LIMIT greatest(coalesce(p_limit, 0), 0)
$$;

-- ── ⑤ 一张图的结果一次写完 ───────────────────────────────────────────
-- p_state: {note_id, project_id, source_column, file_sha, n_files, file_kind, file_bytes, width, height, status,
--           bank_version, bank_sha256, model, outcome}
--   outcome = final   结果定了 (answered / not_a_cover / first_is_video / too_large / decode_failed), 不再重试
--           = counted 算数的失败 (download_failed / no_answer): attempts + 1, 约 20 小时后再试, 第二次之后约 44 小时, 满 3 次不再试
--           = infra   不算数的失败 (download_failed 里的网络问题 / model_failed): attempts 不动, 约 20 小时后再试
--   不管哪种 tries 都 + 1, 满 6 次不再试。图换了或题库版本换了, 两个数从头算。
-- p_rows: note_feature_answers 的行 (数组)。只收这一篇、run_tag = img-primary、题号 img_ 开头、同一个题库版本的行;
--   answered 才许带别的题; not_a_cover 只许带 img_kind 那一行; 其余状态不许带行。
--   answered 必须带一行 img_kind = 封面: 「模型说不是封面的帖不存能用的特征」这一条在库里也守一道。
-- 先删这一篇原有的首图答案再写新的, 和状态行在同一个事务里: 不会出现「状态说答完了, 答案却是上一张图的」。
-- 回 final / retry / quarantined。
CREATE OR REPLACE FUNCTION truth_vault.write_first_image_result(p_state JSONB, p_rows JSONB)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_note     TEXT;
    v_status   TEXT;
    v_outcome  TEXT;
    v_bank     TEXT;
    v_rows     JSONB := coalesce(p_rows, '[]'::jsonb);
    v_old      truth_vault.note_first_image%ROWTYPE;
    v_same     BOOLEAN := false;
    v_attempts INT;
    v_tries    INT;
    v_next     TIMESTAMPTZ;
BEGIN
    IF jsonb_typeof(p_state) IS DISTINCT FROM 'object' OR jsonb_typeof(v_rows) <> 'array' THEN
        RAISE EXCEPTION 'first image: state must be an object and rows an array';
    END IF;
    v_note := p_state ->> 'note_id';  v_status := p_state ->> 'status';
    v_outcome := p_state ->> 'outcome';  v_bank := p_state ->> 'bank_version';
    IF v_outcome IS NULL OR v_outcome NOT IN ('final', 'counted', 'infra') THEN
        RAISE EXCEPTION 'first image: bad outcome';
    END IF;
    IF NOT ((v_outcome = 'final'   AND v_status IN ('answered', 'not_a_cover', 'first_is_video', 'too_large', 'decode_failed'))
         OR (v_outcome = 'counted' AND v_status IN ('download_failed', 'no_answer'))
         OR (v_outcome = 'infra'   AND v_status IN ('download_failed', 'model_failed'))) THEN
        RAISE EXCEPTION 'first image: status and outcome do not go together';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM truth_vault.notes
                   WHERE note_id = v_note AND project_id = p_state ->> 'project_id') THEN
        RAISE EXCEPTION 'first image: note/project mismatch';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_rows) r
               WHERE r ->> 'subject_type' IS DISTINCT FROM 'note'
                  OR r ->> 'subject_id' IS DISTINCT FROM v_note
                  OR r ->> 'run_tag' IS DISTINCT FROM 'img-primary'
                  OR r ->> 'bank_version' IS DISTINCT FROM v_bank
                  OR coalesce(r ->> 'question_id', '') NOT LIKE 'img\_%') THEN
        RAISE EXCEPTION 'first image: rows must be img_ answers of this note under run_tag img-primary';
    END IF;
    IF v_status NOT IN ('answered', 'not_a_cover') AND jsonb_array_length(v_rows) > 0 THEN
        RAISE EXCEPTION 'first image: this status carries no answers';
    END IF;
    IF v_status = 'not_a_cover' AND EXISTS (SELECT 1 FROM jsonb_array_elements(v_rows) r
                                           WHERE r ->> 'question_id' <> 'img_kind' OR r ->> 'answer' = '封面') THEN
        RAISE EXCEPTION 'first image: not_a_cover may only carry the img_kind row';
    END IF;
    IF v_status = 'answered' AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_rows) r
                                            WHERE r ->> 'question_id' = 'img_kind' AND r ->> 'answer' = '封面') THEN
        RAISE EXCEPTION 'first image: answered needs img_kind = cover';
    END IF;

    SELECT * INTO v_old FROM truth_vault.note_first_image WHERE note_id = v_note FOR UPDATE;
    IF FOUND THEN
        v_same := v_old.file_sha = p_state ->> 'file_sha' AND v_old.bank_version = v_bank;
    END IF;
    v_tries    := CASE WHEN v_same THEN v_old.tries ELSE 0 END + 1;
    v_attempts := CASE WHEN v_same THEN v_old.attempts ELSE 0 END + CASE WHEN v_outcome = 'counted' THEN 1 ELSE 0 END;
    v_next := CASE WHEN v_outcome = 'final' OR v_attempts >= 3 OR v_tries >= 6 THEN NULL
                   WHEN v_outcome = 'counted' AND v_attempts >= 2 THEN now() + interval '44 hours'
                   ELSE now() + interval '20 hours' END;

    DELETE FROM truth_vault.note_feature_answers
     WHERE subject_type = 'note' AND subject_id = v_note AND run_tag = 'img-primary' AND question_id LIKE 'img\_%';
    INSERT INTO truth_vault.note_feature_answers
        (subject_type, subject_id, question_id, question_version, bank_version, bank_sha256,
         extractor, run_tag, answer, evidence, prob, invalid_reason, extracted_at)
    SELECT subject_type, subject_id, question_id, question_version, bank_version, bank_sha256,
           extractor, run_tag, answer, NULL, NULL, invalid_reason, now()
    FROM jsonb_populate_recordset(NULL::truth_vault.note_feature_answers, v_rows);

    INSERT INTO truth_vault.note_first_image AS t
        (note_id, project_id, source_column, file_sha, n_files, file_kind, file_bytes, width, height,
         status, bank_version, bank_sha256, model, attempts, tries, next_try_at)
    VALUES (v_note, p_state ->> 'project_id', p_state ->> 'source_column', p_state ->> 'file_sha',
            (p_state ->> 'n_files')::int, p_state ->> 'file_kind', (p_state ->> 'file_bytes')::bigint,
            (p_state ->> 'width')::int, (p_state ->> 'height')::int,
            v_status, v_bank, p_state ->> 'bank_sha256', p_state ->> 'model', v_attempts, v_tries, v_next)
    ON CONFLICT (note_id) DO UPDATE
       SET project_id = excluded.project_id, source_column = excluded.source_column, file_sha = excluded.file_sha,
           n_files = excluded.n_files, file_kind = excluded.file_kind, file_bytes = excluded.file_bytes,
           width = excluded.width, height = excluded.height, status = excluded.status,
           bank_version = excluded.bank_version, bank_sha256 = excluded.bank_sha256, model = excluded.model,
           attempts = excluded.attempts, tries = excluded.tries, next_try_at = excluded.next_try_at,
           updated_at = now();
    RETURN CASE WHEN v_outcome = 'final' THEN 'final' WHEN v_next IS NULL THEN 'quarantined' ELSE 'retry' END;
END $$;

-- ── ⑥ 题库名单的镜像 ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION truth_vault.sync_first_image_bank(
    p_bank_version TEXT, p_bank_sha256 TEXT, p_confirmed TEXT[], p_excluded TEXT[], p_surfaced TEXT[]
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF coalesce(p_bank_version, '') = '' OR coalesce(p_bank_sha256, '') = '' THEN
        RAISE EXCEPTION 'first image: bank version and checksum are required';
    END IF;
    INSERT INTO truth_vault.first_image_bank_state AS b
        (id, bank_version, bank_sha256, cover_confirmed_projects, excluded_projects, surfaced_questions, synced_at)
    VALUES (true, p_bank_version, p_bank_sha256, coalesce(p_confirmed, '{}'), coalesce(p_excluded, '{}'),
            coalesce(p_surfaced, '{}'), now())
    ON CONFLICT (id) DO UPDATE
       SET bank_version = excluded.bank_version, bank_sha256 = excluded.bank_sha256,
           cover_confirmed_projects = excluded.cover_confirmed_projects,
           excluded_projects = excluded.excluded_projects,
           surfaced_questions = excluded.surfaced_questions, synced_at = now();
END $$;

REVOKE ALL ON FUNCTION truth_vault.first_image_candidates(TEXT,TIMESTAMP,TEXT[],BOOLEAN,INT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION truth_vault.write_first_image_result(JSONB,JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION truth_vault.sync_first_image_bank(TEXT,TEXT,TEXT[],TEXT[],TEXT[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION truth_vault.first_image_candidates(TEXT,TIMESTAMP,TEXT[],BOOLEAN,INT) TO service_role;
GRANT EXECUTE ON FUNCTION truth_vault.write_first_image_result(JSONB,JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION truth_vault.sync_first_image_bank(TEXT,TEXT,TEXT[],TEXT[],TEXT[]) TO service_role;

-- ── ⑦ 给下游读的那一面 ───────────────────────────────────────────────
-- 每篇做过的帖一行 (没做过的帖没有行)。契约见 docs/34-first-image-pass.md 第 6 节; 列只加不改。
--   usable            这一篇的首图答案能不能用: status = answered、不是「多图且没人确认」、项目没被列为先不做、
--                     题库镜像那一行在而且版本对得上、做完之后首图没换也没被拿掉。别的情况都是 false。
--   cover_unconfirmed 多图的帖 (n_files > 1), 而且它的项目不在 cover_confirmed_projects 里。只有一张图的帖永远是 false。
--                     题库镜像那一行不在时, 多图的帖一律 true。
--   project_excluded  这一篇的项目现在在 excluded_projects 里 (镜像那一行不在时是 false, 但 usable 照样是 false)。
--   n_files           帖子【现在】那一列里有几个附件 (读的那一刻从 v_note_first_image_source 数的, 不是做的时候记下的数):
--                     做完之后运营又加了图, 这里和 cover_unconfirmed 立刻跟着变。图片列整个没了时, 给做的时候记下的数。
--   answers           usable 为 true 时是一个对象 {题号: 答案}, 只含 surfaced_questions 里的题, 而且只含答成了的题
--                     (一道题没答成 = 对象里没有这个键; 一道都没有 = 空对象)。usable 为 false 时是 NULL。
--   image_changed     做完之后第一个附件换了, 或者图片列没了: 库里的答案是给旧图答的, 不能用 (换了图的下一晚会重做)。
CREATE OR REPLACE VIEW truth_vault.v_first_image_features
WITH (security_invoker = true) AS
SELECT s.note_id,
       s.project_id,
       s.status,
       f.usable,
       f.cover_unconfirmed,
       f.project_excluded,
       cur.n_files,
       s.bank_version,
       s.model,
       s.updated_at AS checked_at,
       CASE WHEN f.usable THEN coalesce((
           SELECT jsonb_object_agg(a.question_id, a.answer)
           FROM truth_vault.note_feature_answers a
           WHERE a.subject_type = 'note' AND a.subject_id = s.note_id AND a.run_tag = 'img-primary'
             AND a.bank_version = s.bank_version AND a.answer IS NOT NULL
             AND a.question_id = ANY (b.surfaced_questions)
       ), '{}'::jsonb) END AS answers,
       cur.image_changed
FROM truth_vault.note_first_image s
LEFT JOIN truth_vault.v_note_first_image_source src ON src.note_id = s.note_id
LEFT JOIN truth_vault.first_image_bank_state b ON b.id
CROSS JOIN LATERAL (
    SELECT coalesce(src.n_files, s.n_files) AS n_files,
           (src.note_id IS NULL OR src.file_sha <> s.file_sha) AS image_changed
) cur
CROSS JOIN LATERAL (
    SELECT (cur.n_files > 1 AND NOT (s.project_id = ANY (coalesce(b.cover_confirmed_projects, '{}'::text[])))) AS cover_unconfirmed,
           (s.project_id = ANY (coalesce(b.excluded_projects, '{}'::text[]))) AS project_excluded
) g
CROSS JOIN LATERAL (
    SELECT g.cover_unconfirmed, g.project_excluded,
           (s.status = 'answered' AND b.id IS NOT NULL AND b.bank_version = s.bank_version
            AND NOT g.cover_unconfirmed AND NOT g.project_excluded AND NOT cur.image_changed) AS usable
) f;
REVOKE ALL ON truth_vault.v_first_image_features FROM PUBLIC, anon, authenticated;
GRANT SELECT ON truth_vault.v_first_image_features TO service_role;
COMMENT ON VIEW truth_vault.v_first_image_features IS
    '首图特征给下游读的那一面 (v1.28): 每篇做过的帖一行。usable = true 才有 answers ({题号: 答案}, 只含往外给的题里答成了的); '
    '不是封面、多图且没人确认 (cover_unconfirmed)、项目先不做 (project_excluded)、没答成的、做完之后首图换了或没了的 (image_changed), '
    'answers 是 NULL。n_files / cover_unconfirmed / image_changed 是读的那一刻按帖子现在的图片列算的。'
    '答案对不对没有人对着图核过 (只验过同一个模型两轮一致)。契约: docs/34-first-image-pass.md 第 6 节。';
COMMIT;
