-- truth_vault v1.22 · 投流证据链 F1/F2: 投流事件、隔离、前后读数 —— 全是视图 (D-133, G-15 证据部分, 2026-10-29)
-- ════════════════════════════════════════════════════════════════════
-- 背景: owner 10-29「TV 功能说明: 投流证据链」。投流标记今天只写成一个布尔 (data_quality_flags.paid_promoted,
--   sync_feishu_notes_to_truth_vault.py A4), 没有日期、没有前后读数; 运营 09-22 的例子 (SPX 9/16 778 / 73) 是人手翻
--   audit_log 拼出来的。这份迁移把「哪篇、哪天投的、投之前 / 之后各读到多少」做成可复查的视图, 不加表、不加夜跑步骤。
-- 判据 (Python 同一份在 _common.classify_paid_element; 两边逐字一致由 scripts/check_paid_boost.py 的 parity 段守):
--   · 只读白名单列: raw_extra 的「维护情况」「关注情况」「维护时间」「维护效果」(顶层没值才看 _undeclared, 同 sync 的 _cm_cell)
--     和 _tier_source_raw。从不扫整个 raw_extra / data_quality_flags 的文本 —— 生产里「帐号昵称」「评论区快照」、标题正文、
--     paid_promoted_reason 都带 🍟 (RIO / ANSHEN / XIWU_phase2 / NUC), 一扫就错。
--   · 按【元素】精确匹配: 「M/D🍟」= 带日期的投流 (日期 = 🍟 前那段); 「已投流，等回收数据」和 tier 源元素「关注后续流量」
--     = 没日期的投流 → 隔离; 别的带 🍟 / 投流 / 薯条 / 关注后续流量 的元素 (准备投流、不投流、整串「关注后续流量 爆贴」)
--     = 认不出 → 隔离, 不算投流。
--   · 来源 B (owner Q1): 「维护时间」第 i 个元素配「维护效果」第 i 个、且后者是纯数字, 才算一次投流, 日期 = 维护时间。
--     两列元素个数对不上 → 隔离; 维护时间配不上数字效果 (SPX 的控评日期、铺评那几行) → 不算, 只在元素视图里看得见。
--     来源 B 不写 paid_promoted (D-128 / 闸二敏感性数字不变)。
--   · 没年份的日期按北京发布日补年 (同年; 早于发布日就看下一年, 下一年还没到 → 早于发布, 隔离), 再两头核:
--     早于发布日 / 晚于今天 / 🍟 日期晚于 TV 第一次看到这个元素的那天 → 隔离。不猜。
--   · 隔离是视图: 运营补了日期, 下一次读就从隔离挪进事件, 不用审核流程 (owner Q9, 偏离「隔离表」写法, D-133 记了)。
--   · 前后读数 (F2) 只读 audit_log: 一次「读到」= 一次完整同步盖了 last_seen_run_id 的那一行 (同一北京日取最后一次);
--     基线 = 投流日【之前】最后一次, 投流当天单列 (k=0, 前后不知道), D+1 / D+3 / D+7 只认正好那天, 不向邻日借;
--     没有就写 missing:<原因>, 从不写 0。曝光 / 阅读 / 互动在投流日之后没变、截图 file_token 也没换 → missing:no_rescreenshot。
-- 挡不住什么: 运营投了流一个标记都没打; 发布后 0-2 天就投的没有基线; 曝光总数里含投流量; 评论增量里混着铺评
--   (comment_maintained_seeded 并排给); 夜跑粒度 + 投流当天前后不明; note_id 换号 (D-129) 把历史切成两段; tier 是 TV 的
--   tier (UPSERT 保护, 整批翻转闸挡住的那晚不写); 飞书里删掉的标记从视图里一起消失 (verify #100 看 paid_promoted 真→非真)。
-- 消费者: 人 / 读数报告 (data-analysis/paid-boost-evidence-readout-*.md) · verify_supabase_state.sql #98–#100 · CI check_paid_boost.sql。
--   不进 public、没有 v_dash_* (F4 再定曝光面)。truth_vault 的默认权限只给 service_role。
-- 在 notes_v1_9 (last_seen 两列) / notes_v1_12 (comments_count) / notes_v1_21 (v_notes_vanished) 之后应用; 只建函数与视图, 幂等。
-- ════════════════════════════════════════════════════════════════════


-- ── 函数 1 · 安全建日期: 2/30 这类日历上不存在的日子返回 NULL, 不让一个坏格子把整张视图炸掉 ─────────────
CREATE OR REPLACE FUNCTION truth_vault.tv_safe_date(y int, m int, d int) RETURNS date
    LANGUAGE plpgsql IMMUTABLE
    SET search_path = ''
AS $$
BEGIN
    RETURN make_date(y, m, d);
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR numeric_value_out_of_range THEN
    RETURN NULL;
END;
$$;


-- ── 函数 2 · 取一个 raw_extra 格子: 顶层有值用顶层, 顶层空 (缺键 / null / "" / []) 才看 _undeclared ─────────────
--   同 sync_feishu_notes_to_truth_vault.py 的 _cm_cell。
CREATE OR REPLACE FUNCTION truth_vault.tv_raw_cell(raw_extra jsonb, col text) RETURNS jsonb
    LANGUAGE sql IMMUTABLE
    SET search_path = ''
AS $$
    SELECT coalesce(nullif(nullif(nullif(raw_extra -> col, 'null'::jsonb), '""'::jsonb), '[]'::jsonb),
                    raw_extra -> '_undeclared' -> col);
$$;


-- ── 函数 3 · 把一个格子拆成元素 (Python 同一份: _common.paid_cell_elements) ─────────────
--   数组: 每个元素一个 (字符串原样, 数字取文本, JSON null 跳过); 数组里只要有对象 = 飞书文本格 [{text,type}…],
--   拼起来算【一个】元素; 单个字符串 / 数字 = 一个元素; 对象只认 text; null / "" / [] = 没有元素。
--   每个元素去掉首尾空白 (空格 / \t / \r / \n), 去完是空串的跳过; ord 从 1 数, 只数留下的。
--   elem 留原 JSON (数字还是数字, 日期解析要分), txt 是去完空白的文本。
CREATE OR REPLACE FUNCTION truth_vault.tv_cell_elements(cell jsonb)
    RETURNS TABLE (ord int, elem jsonb, txt text)
    LANGUAGE plpgsql IMMUTABLE
    ROWS 3
    SET search_path = ''
AS $$
DECLARE
    x jsonb;
    t text;
    joined text := '';
    n int := 0;
BEGIN
    IF cell IS NULL OR jsonb_typeof(cell) = 'null' THEN
        RETURN;
    END IF;
    IF jsonb_typeof(cell) = 'array' THEN
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(cell) AS y(v) WHERE jsonb_typeof(y.v) = 'object') THEN
            FOR x IN SELECT y.v FROM jsonb_array_elements(cell) WITH ORDINALITY AS y(v, o) ORDER BY y.o LOOP
                joined := joined || coalesce(CASE WHEN jsonb_typeof(x) = 'object' THEN x ->> 'text'
                                                  ELSE x #>> '{}' END, '');
            END LOOP;
            t := btrim(joined, E' \t\r\n');
            IF t <> '' THEN
                ord := 1; elem := to_jsonb(t); txt := t;
                RETURN NEXT;
            END IF;
            RETURN;
        END IF;
        FOR x IN SELECT y.v FROM jsonb_array_elements(cell) WITH ORDINALITY AS y(v, o) ORDER BY y.o LOOP
            t := btrim(coalesce(x #>> '{}', ''), E' \t\r\n');
            CONTINUE WHEN t = '';
            n := n + 1;
            ord := n; elem := x; txt := t;
            RETURN NEXT;
        END LOOP;
        RETURN;
    END IF;
    IF jsonb_typeof(cell) = 'object' THEN
        t := btrim(coalesce(cell ->> 'text', ''), E' \t\r\n');
        IF t <> '' THEN
            ord := 1; elem := to_jsonb(t); txt := t;
            RETURN NEXT;
        END IF;
        RETURN;
    END IF;
    t := btrim(coalesce(cell #>> '{}', ''), E' \t\r\n');
    IF t <> '' THEN
        ord := 1; elem := cell; txt := t;
        RETURN NEXT;
    END IF;
END;
$$;


-- ── 函数 4 · 拆 _tier_source_raw: 它是 sync 写的 Python str(), 不是 JSON ─────────────
--   "['关注后续流量', '爆贴']" → 两个元素; "[{'text': 'x', 'type': 'text'}]" (文本格) → 拼成一个元素;
--   不是 [...] 形、或里面没有引号的 → 整串一个元素。Python 那边直接拿 intermediates 里的原值拆, 结果相同。
--   反转义只做 \x → x (够用: 投流标记里没有引号和反斜杠)。
CREATE OR REPLACE FUNCTION truth_vault.tv_pyrepr_elements(s text)
    RETURNS TABLE (ord int, txt text)
    LANGUAGE plpgsql IMMUTABLE
    ROWS 3
    SET search_path = ''
AS $$
DECLARE
    t text := btrim(coalesce(s, ''), E' \t\r\n');
    m text[];
    v text;
    joined text := '';
    n int := 0;
BEGIN
    IF t = '' THEN
        RETURN;
    END IF;
    IF left(t, 1) = '[' AND right(t, 1) = ']' AND t ~ '[''"]' THEN
        IF t ~ '^\[\s*\{' THEN
            FOR m IN SELECT regexp_matches(t, $r$['"]text['"]\s*:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")$r$, 'g') LOOP
                joined := joined || regexp_replace(coalesce(m[1], m[2], ''), '\\(.)', '\1', 'g');
            END LOOP;
            v := btrim(joined, E' \t\r\n');
            IF v <> '' THEN
                ord := 1; txt := v;
                RETURN NEXT;
            END IF;
            RETURN;
        END IF;
        FOR m IN SELECT regexp_matches(t, $r$'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"$r$, 'g') LOOP
            v := btrim(regexp_replace(coalesce(m[1], m[2], ''), '\\(.)', '\1', 'g'), E' \t\r\n');
            CONTINUE WHEN v = '';
            n := n + 1;
            ord := n; txt := v;
            RETURN NEXT;
        END LOOP;
        RETURN;
    END IF;
    ord := 1; txt := t;
    RETURN NEXT;
END;
$$;


-- ── 函数 5 · 给一个元素定类 (Python 同一份: _common.classify_paid_element; 字面量逐字相同, CI parity 段比对) ─────────────
--   paid_dated / paid_undated = 投流标记 (sync 写 paid_promoted=true 的只有这两类);
--   marker_like_unrecognized = 像标记但认不出 → 隔离, paid_promoted 不写 (owner Q8);
--   non_paid = 维护情况 / 关注情况 里的其他取值 (关注、✅、控评&置顶✅ …), 只列出来备查;
--   ops_date / ops_effect_numeric / ops_effect_other = 来源 B 的两列; 白名单外的列 → NULL。
CREATE OR REPLACE FUNCTION truth_vault.tv_classify_paid_element(col text, txt text) RETURNS text
    LANGUAGE sql IMMUTABLE
    SET search_path = ''
AS $$
    SELECT CASE
        WHEN col IN ('维护情况', '关注情况') THEN
            CASE WHEN txt ~ '^([0-9]{1,2})/([0-9]{1,2}) *🍟$' THEN 'paid_dated'
                 WHEN txt IN ('已投流，等回收数据') THEN 'paid_undated'
                 WHEN txt ~ '🍟|投流|薯条|关注后续流量' THEN 'marker_like_unrecognized'
                 ELSE 'non_paid' END
        WHEN col = '_tier_source_raw' THEN
            CASE WHEN txt IN ('关注后续流量') THEN 'paid_undated'
                 WHEN txt ~ '🍟|投流|薯条|关注后续流量' THEN 'marker_like_unrecognized'
                 ELSE 'non_paid' END
        WHEN col = '维护时间' THEN 'ops_date'
        WHEN col = '维护效果' THEN
            CASE WHEN txt ~ '^[0-9]+(\.[0-9]+)?$' THEN 'ops_effect_numeric' ELSE 'ops_effect_other' END
    END;
$$;


-- ── 函数 6 · 解析一个投流日期: 返回 (d, year_rule, problem); problem 非空 = 进隔离 ─────────────
--   JSON 数字 = 毫秒时间戳 (2000–2100 之外不认), 按北京日算, year_rule = epoch_ms;
--   「YYYY/M/D」「YYYY-M-D」「YYYY.M.D」= explicit;
--   「M/D🍟」「M月D日」「M/D」没有年 = publish_anchor: 先取北京发布日那年, 早于发布日就看下一年
--     (publish_anchor_next_year, 只认跨年: 12 月发、1 月投, 下一年那天离发布 ≤ 92 天且已经到了), 否则 → before_publish
--     (d 给同年那天, 只作参考; 不随今天变);
--   发布日未知 → year_unresolvable; 别的写法 / 日历上没有的日子 → unparseable_date;
--   然后两头核: 早于发布日 → before_publish, 晚于今天 → date_in_future。
--   today 由调用方传 (视图传北京今天, CI 传定值), 所以函数是 IMMUTABLE、可以逐例测。
CREATE OR REPLACE FUNCTION truth_vault.tv_parse_ops_date(elem jsonb, anchor date, today date,
                                                         OUT d date, OUT year_rule text, OUT problem text)
    LANGUAGE plpgsql IMMUTABLE
    SET search_path = ''
AS $$
DECLARE
    s text;
    m text[];
    n numeric;
    d_same date;
    d_next date;
BEGIN
    IF elem IS NULL OR jsonb_typeof(elem) NOT IN ('number', 'string') THEN
        problem := 'unparseable_date';
        RETURN;
    END IF;
    IF jsonb_typeof(elem) = 'number' THEN
        n := (elem #>> '{}')::numeric;
        year_rule := 'epoch_ms';
        IF n < 946684800000 OR n >= 4102444800000 THEN
            problem := 'unparseable_date';
            RETURN;
        END IF;
        d := (to_timestamp((n / 1000.0)::double precision) AT TIME ZONE 'Asia/Shanghai')::date;
    ELSE
        s := btrim(elem #>> '{}', E' \t\r\n');
        m := regexp_match(s, '^([0-9]{4})[/.-]([0-9]{1,2})[/.-]([0-9]{1,2})$');
        IF m IS NOT NULL THEN
            year_rule := 'explicit';
            d := truth_vault.tv_safe_date(m[1]::int, m[2]::int, m[3]::int);
            IF d IS NULL THEN
                problem := 'unparseable_date';
                RETURN;
            END IF;
        ELSE
            m := coalesce(regexp_match(s, '^([0-9]{1,2})/([0-9]{1,2}) *🍟$'),
                          regexp_match(s, '^([0-9]{1,2})月([0-9]{1,2})日?$'),
                          regexp_match(s, '^([0-9]{1,2})/([0-9]{1,2})$'));
            IF m IS NULL THEN
                problem := 'unparseable_date';
                RETURN;
            END IF;
            year_rule := 'publish_anchor';
            IF anchor IS NULL THEN
                problem := 'year_unresolvable';
                RETURN;
            END IF;
            d_same := truth_vault.tv_safe_date(extract(year FROM anchor)::int, m[1]::int, m[2]::int);
            d_next := truth_vault.tv_safe_date(extract(year FROM anchor)::int + 1, m[1]::int, m[2]::int);
            IF d_same IS NULL AND d_next IS NULL THEN
                problem := 'unparseable_date';
                RETURN;
            ELSIF d_same IS NOT NULL AND d_same >= anchor THEN
                d := d_same;
            ELSIF d_next IS NOT NULL AND d_next <= today AND d_next - anchor <= 92 THEN
                -- 只认跨年那一种(12 月发、1 月投): 下一年那天离发布不过一季。不设上限的话, 一条早于发布日的手误
                -- (隔离着的 before_publish)到了明年那一天就变成「发布一年后投流」的事件(复审 on D-133)
                d := d_next;
                year_rule := 'publish_anchor_next_year';
            ELSIF d_same IS NOT NULL THEN
                d := d_same;
                problem := 'before_publish';
                RETURN;
            ELSE
                d := d_next;
                problem := 'date_in_future';
                RETURN;
            END IF;
        END IF;
    END IF;
    IF anchor IS NOT NULL AND d < anchor THEN
        problem := 'before_publish';
    ELSIF today IS NOT NULL AND d > today THEN
        problem := 'date_in_future';
    END IF;
END;
$$;


-- ════════════════════════════════════════════════════════════════════
-- 视图 1 · v_paid_marker_elements: 每篇 × 白名单列 × 元素一行 —— 每一条排除都在这里看得见
-- ════════════════════════════════════════════════════════════════════
--   outcome: event (进事件) / quarantine (进隔离, reason 说为什么) / excluded (不算, reason 说为什么) / context (配对用的效果值)。
--   tier 源里不像标记的元素 (爆贴、标 …) 不列, 不然每篇都有一两行。
--   first_seen_cn_day = TV 第一次在 audit_log 的 raw_extra 里看到这一列有这个元素的北京日 (按同一个拆元素规则比, 不扫文本);
--   只对标记和配上的维护时间算。🍟 的日期晚于它 → date_after_first_seen (标记先于投流出现, 自相矛盾)。
--   来源 B 不做这条: 维护时间可能先填计划日期, 效果是事后补的。
CREATE OR REPLACE VIEW truth_vault.v_paid_marker_elements AS
WITH cls AS MATERIALIZED (
    -- 四列: 每个元素都列 (只有声明了这些列的篇才有行)
    SELECT n.note_id, n.project_id,
           (n.publish_time + interval '8 hours')::date AS publish_cn_date,
           (now() AT TIME ZONE 'Asia/Shanghai')::date AS today_cn,
           c.col AS source_col, e.ord, e.elem, e.txt,
           truth_vault.tv_raw_cell(n.raw_extra, c.col) AS raw_cell,
           CASE c.col WHEN '维护时间' THEN truth_vault.tv_raw_cell(n.raw_extra, '维护效果')
                      WHEN '维护效果' THEN truth_vault.tv_raw_cell(n.raw_extra, '维护时间') END AS counterpart_cell,
           truth_vault.tv_classify_paid_element(c.col, e.txt) AS class
    FROM truth_vault.notes n
    CROSS JOIN (VALUES ('维护情况'), ('关注情况'), ('维护时间'), ('维护效果')) AS c(col)
    CROSS JOIN LATERAL truth_vault.tv_cell_elements(truth_vault.tv_raw_cell(n.raw_extra, c.col)) AS e
    -- 预筛 (只省事, 不改结果): 顶层和 _undeclared 都没有这四个键的篇不可能有元素
    WHERE n.raw_extra ?| ARRAY['维护情况', '关注情况', '维护时间', '维护效果']
       OR n.raw_extra -> '_undeclared' ?| ARRAY['维护情况', '关注情况', '维护时间', '维护效果']
    UNION ALL
    -- tier 源: 只列像标记的元素 (每篇都有 tier 源, 全列会淹掉别的)
    SELECT n.note_id, n.project_id,
           (n.publish_time + interval '8 hours')::date,
           (now() AT TIME ZONE 'Asia/Shanghai')::date,
           '_tier_source_raw', e.ord, to_jsonb(e.txt), e.txt,
           n.raw_extra -> '_tier_source_raw',
           NULL::jsonb,
           truth_vault.tv_classify_paid_element('_tier_source_raw', e.txt)
    FROM truth_vault.notes n
    CROSS JOIN LATERAL truth_vault.tv_pyrepr_elements(n.raw_extra ->> '_tier_source_raw') AS e
    WHERE truth_vault.tv_classify_paid_element('_tier_source_raw', e.txt) <> 'non_paid'
),
ops AS (
    SELECT note_id,
           count(*) FILTER (WHERE source_col = '维护时间') AS n_dates,
           count(*) FILTER (WHERE source_col = '维护效果') AS n_effects,
           count(*) FILTER (WHERE class = 'ops_effect_numeric') AS n_numeric
    FROM cls
    WHERE source_col IN ('维护时间', '维护效果')
    GROUP BY note_id
),
paired AS (
    SELECT l.*,
           eff.elem AS paired_effect,
           eff.txt AS paired_effect_txt,
           CASE
               WHEN l.source_col = '维护时间' THEN
                   CASE WHEN o.n_dates = o.n_effects AND eff.class = 'ops_effect_numeric' THEN 'paired'
                        WHEN o.n_numeric > 0 AND o.n_dates <> o.n_effects THEN 'count_mismatch'
                        ELSE 'unpaired' END
               WHEN l.source_col = '维护效果' THEN
                   CASE WHEN l.class <> 'ops_effect_numeric' THEN 'not_numeric'
                        WHEN o.n_dates = 0 THEN 'no_date'
                        WHEN o.n_dates = o.n_effects THEN 'paired'
                        ELSE 'count_mismatch' END
           END AS pairing
    FROM cls l
    LEFT JOIN ops o ON o.note_id = l.note_id
    LEFT JOIN cls eff
           ON l.source_col = '维护时间' AND eff.note_id = l.note_id
          AND eff.source_col = '维护效果' AND eff.ord = l.ord
),
parsed AS (
    SELECT p.*, pd.d AS parsed_date, pd.year_rule, pd.problem AS date_problem,
           (p.class IN ('paid_dated', 'paid_undated', 'marker_like_unrecognized')
            OR (p.class = 'ops_date' AND p.pairing IN ('paired', 'count_mismatch'))) AS needs_first_seen
    FROM paired p
    LEFT JOIN LATERAL truth_vault.tv_parse_ops_date(p.elem, p.publish_cn_date, p.today_cn) AS pd
           ON p.class IN ('paid_dated', 'ops_date')
),
seen AS (
    SELECT pr.*, fs.first_seen_cn_day
    FROM parsed pr
    LEFT JOIN LATERAL (
        SELECT min((a.occurred_at + interval '8 hours')::date) AS first_seen_cn_day
        FROM truth_vault.audit_log a
        CROSS JOIN LATERAL (
            SELECT CASE WHEN a.operation = 'INSERT' THEN a.changed_cols -> 'raw_extra'
                        ELSE a.changed_cols -> 'raw_extra' -> 1 END AS blob
        ) b
        WHERE pr.needs_first_seen
          AND a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.row_id = pr.note_id
          AND a.operation IN ('INSERT', 'UPDATE') AND a.changed_cols ? 'raw_extra'
          AND CASE WHEN pr.source_col = '_tier_source_raw'
                   THEN EXISTS (SELECT 1 FROM truth_vault.tv_pyrepr_elements(b.blob ->> '_tier_source_raw') x
                                WHERE x.txt = pr.txt)
                   ELSE EXISTS (SELECT 1 FROM truth_vault.tv_cell_elements(truth_vault.tv_raw_cell(b.blob, pr.source_col)) x
                                WHERE x.txt = pr.txt)
              END
    ) fs ON true
),
judged AS (
    SELECT s.*,
           CASE
               WHEN s.class = 'non_paid' THEN 'excluded'
               WHEN s.class IN ('marker_like_unrecognized', 'paid_undated') THEN 'quarantine'
               WHEN s.class = 'paid_dated' THEN
                   CASE WHEN s.date_problem IS NOT NULL THEN 'quarantine'
                        WHEN s.first_seen_cn_day IS NOT NULL AND s.parsed_date > s.first_seen_cn_day THEN 'quarantine'
                        ELSE 'event' END
               WHEN s.class = 'ops_date' THEN
                   CASE s.pairing WHEN 'unpaired' THEN 'excluded'
                                  WHEN 'count_mismatch' THEN 'quarantine'
                                  ELSE CASE WHEN s.date_problem IS NOT NULL THEN 'quarantine' ELSE 'event' END END
               WHEN s.class = 'ops_effect_numeric' THEN
                   CASE WHEN s.pairing = 'no_date' THEN 'quarantine' ELSE 'context' END
               ELSE 'excluded'
           END AS outcome,
           CASE
               WHEN s.class = 'non_paid' THEN 'non_paid'
               WHEN s.class = 'marker_like_unrecognized' THEN 'marker_like_unrecognized'
               WHEN s.class = 'paid_undated' THEN 'no_date'
               WHEN s.class = 'paid_dated' THEN
                   CASE WHEN s.date_problem IS NOT NULL THEN s.date_problem
                        WHEN s.first_seen_cn_day IS NOT NULL AND s.parsed_date > s.first_seen_cn_day THEN 'date_after_first_seen'
                   END
               WHEN s.class = 'ops_date' THEN
                   CASE s.pairing WHEN 'unpaired' THEN 'ops_date_unpaired'
                                  WHEN 'count_mismatch' THEN 'time_effect_count_mismatch'
                                  ELSE s.date_problem END
               WHEN s.class = 'ops_effect_numeric' THEN
                   CASE s.pairing WHEN 'no_date' THEN 'no_date'
                                  WHEN 'count_mismatch' THEN 'time_effect_count_mismatch' END
               WHEN s.class = 'ops_effect_other' THEN 'ops_effect_not_numeric'
           END AS reason
    FROM seen s
)
SELECT note_id, project_id, source_col, ord,
       txt AS raw_elem, raw_cell, class, pairing,
       paired_effect, paired_effect_txt, counterpart_cell,
       parsed_date, year_rule, outcome, reason,
       publish_cn_date, first_seen_cn_day
FROM judged;

COMMENT ON VIEW truth_vault.v_paid_marker_elements IS
    '投流证据链 F1 (D-133): 白名单五列逐元素一行 (维护情况 / 关注情况 / 维护时间 / 维护效果 / _tier_source_raw 里像标记的), '
    '带类别、配对、解析出的日期、去向 (event / quarantine / excluded / context) 和原因。每一条排除都在这里看得见; 不扫整个 raw_extra。';


-- ════════════════════════════════════════════════════════════════════
-- 视图 2 · v_paid_boost_events: 一篇一个投流日一行 (同一天在两列都标了 = 一次)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW truth_vault.v_paid_boost_events AS
WITH el AS MATERIALIZED (
    SELECT * FROM truth_vault.v_paid_marker_elements
    WHERE outcome = 'event' OR (class = 'ops_date' AND outcome = 'excluded')
),
ev AS (
    SELECT note_id, project_id, parsed_date AS boost_date,
           array_agg(DISTINCT CASE WHEN class = 'paid_dated' THEN '🍟前日期' ELSE '维护时间' END) AS date_sources,
           array_agg(DISTINCT year_rule) AS year_rules,
           array_agg(DISTINCT source_col) AS marker_cols,
           array_agg(raw_elem ORDER BY source_col, ord) AS marker_raw,
           jsonb_agg(paired_effect ORDER BY ord) FILTER (WHERE paired_effect IS NOT NULL) AS ops_effect_raw,
           array_agg(paired_effect_txt ORDER BY ord) FILTER (WHERE paired_effect_txt IS NOT NULL) AS ops_effect_txt,
           min(first_seen_cn_day) AS first_seen_cn_day
    FROM el
    WHERE outcome = 'event'
    GROUP BY note_id, project_id, parsed_date
),
unpaired AS (
    SELECT DISTINCT note_id, parsed_date
    FROM el
    WHERE class = 'ops_date' AND outcome = 'excluded' AND parsed_date IS NOT NULL
),
x AS (
    SELECT ev.*, n.impressions, n.data_quality_flags,
           (n.publish_time + interval '8 hours')::date AS publish_cn_date,
           truth_vault.tv_raw_cell(n.raw_extra, '起量时间') AS takeoff_cell,
           (now() AT TIME ZONE 'Asia/Shanghai')::date AS today_cn,
           CASE WHEN cardinality(ev.ops_effect_txt) = 1 THEN ev.ops_effect_txt[1]::numeric END AS ops_effect_value
    FROM ev
    JOIN truth_vault.notes n ON n.note_id = ev.note_id
)
SELECT x.note_id || '@' || to_char(x.boost_date, 'YYYY-MM-DD') AS event_id,
       x.note_id, x.project_id, x.boost_date,
       x.date_sources, x.year_rules, x.marker_cols, x.marker_raw,
       x.publish_cn_date,
       x.boost_date - x.publish_cn_date AS days_after_publish,
       x.first_seen_cn_day,
       tk.d AS takeoff_cn_date,
       CASE WHEN x.takeoff_cell IS NULL THEN 'missing'
            WHEN tk.problem IS NOT NULL THEN 'invalid:' || tk.problem
            WHEN tk.d < x.boost_date THEN 'before'
            WHEN tk.d <= x.boost_date + 7 THEN 'in_window'
            ELSE 'after' END AS takeoff_vs_window,
       CASE x.data_quality_flags -> 'paid_promoted'
            WHEN 'true'::jsonb THEN 'yes' WHEN 'false'::jsonb THEN 'no' ELSE 'unknown' END AS paid_promoted_state,
       CASE WHEN jsonb_typeof(x.data_quality_flags -> 'comment_maintained_seeded') = 'number'
            THEN (x.data_quality_flags ->> 'comment_maintained_seeded')::numeric END AS comment_maintained_seeded,
       EXISTS (SELECT 1 FROM unpaired u WHERE u.note_id = x.note_id AND u.parsed_date = x.boost_date) AS ops_date_agrees,
       x.note_id IN (SELECT v.note_id FROM truth_vault.v_notes_vanished v) AS vanished,
       -- ops_* 自成一块: 运营自报的「维护效果」, 不进任何增量 (口径没定, O-06)
       x.ops_effect_raw,
       x.ops_effect_value,
       -- 运营答了 O-06 再按项目加 WHEN x.project_id = '…' THEN 'increment' / 'abs_12h'; 答之前一律 unknown
       CASE WHEN x.ops_effect_raw IS NULL THEN NULL ELSE 'unknown' END AS ops_effect_metric_flag,
       CASE WHEN x.ops_effect_value IS NULL THEN NULL
            WHEN x.impressions IS NULL THEN 'impressions_missing'
            WHEN x.ops_effect_value > x.impressions THEN 'exceeds'
            ELSE 'ok' END AS ops_effect_vs_current_impressions
FROM x
LEFT JOIN LATERAL truth_vault.tv_parse_ops_date(x.takeoff_cell, x.publish_cn_date, x.today_cn) AS tk ON x.takeoff_cell IS NOT NULL;

COMMENT ON VIEW truth_vault.v_paid_boost_events IS
    '投流证据链 F1 (D-133): 一篇一个投流日一行, event_id = note_id@日期。日期来源 🍟前日期 / 维护时间 (配数字效果); '
    'paid_promoted_state 照抄 data_quality_flags (缺键 = unknown); ops_* 是运营自报的维护效果, 口径未定 (metric_flag 一律 unknown, O-06), 不进增量。';


-- ════════════════════════════════════════════════════════════════════
-- 视图 3 · v_paid_boost_quarantine: 有投流标记但定不了日子 / 认不出的元素, 原值照给; 运营补好了自己就出去
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW truth_vault.v_paid_boost_quarantine AS
SELECT q.note_id, q.project_id, q.source_col, q.ord, q.raw_elem, q.raw_cell, q.counterpart_cell,
       q.class, q.reason,
       q.parsed_date AS parsed_date_context,
       q.publish_cn_date,
       q.first_seen_cn_day,
       q.note_id IN (SELECT v.note_id FROM truth_vault.v_notes_vanished v) AS vanished
FROM truth_vault.v_paid_marker_elements q
WHERE q.outcome = 'quarantine';

COMMENT ON VIEW truth_vault.v_paid_boost_quarantine IS
    '投流证据链 F1 隔离 (D-133, 视图不是表: 运营补好了下一次读就挪进事件)。reason: no_date / marker_like_unrecognized / '
    'time_effect_count_mismatch / unparseable_date / year_unresolvable / before_publish / date_in_future / date_after_first_seen。'
    'parsed_date_context 和 first_seen_cn_day 只作参考, 从不当投流日。';


-- ════════════════════════════════════════════════════════════════════
-- 视图 4 · v_paid_boost_readings (F2): 每个事件 × k ∈ {-1 基线, 0 投流当天, 1, 3, 7} 一行, 全部从 audit_log 读
-- ════════════════════════════════════════════════════════════════════
--   occurred_at 是 UTC 的无时区时间戳 → 北京日 = (occurred_at + 8h)::date; 从不和带时区的字面量比。
--   「读到」= 完整同步盖戳的那一行 (UPDATE 带 last_seen_run_id, 或 INSERT 的 last_seen_run_id 非空); 同一北京日取最后一次。
--   v1_9 之前没有戳: 这一篇第一次盖戳之前、且早于 2026-08-31 的任何写入算一次读 (obs_kind = pre_v1_9_any_write)。
--   某个时刻的值 = 那一刻之前最后一次改它的那行 (INSERT 取平铺值, UPDATE 取 ->1); 那之前 audit 里没有改过 → 取之后第一次改的 ->0。
--   评论数: typed comments_count; 它为空且这次读在 2026-09-18 (北京) 之前 → 读 raw_extra 的「实时数据.评论数」(顶层 / _undeclared),
--     comments_source 说用的哪个; comments_measured_at_cn = 同一份 raw_extra 的「最近检查时间」(linkcheck 巡查时刻, 北京)。
--   曝光 / 阅读 / 互动 (k ≥ 0): 投流日 0 点 (北京) 到这次读之间这个数改过、或「相关截图」的 file_token 集合换过才给值,
--     否则 missing:no_rescreenshot, *_changed_cn_day 说值是哪天来的。tmp_url 每晚都变, 不比。
--   状态: ok / missing:not_due / missing:before_history / missing:no_reading_before_boost / missing:no_full_sync_that_day /
--     missing:value_null / missing:value_not_numeric / missing:no_rescreenshot。missing 的值一律 NULL, 从不写 0。
CREATE OR REPLACE VIEW truth_vault.v_paid_boost_readings AS
WITH ev AS MATERIALIZED (
    SELECT event_id, note_id, boost_date,
           boost_date::timestamp - interval '8 hours' AS d0_utc,
           (now() AT TIME ZONE 'Asia/Shanghai')::date AS today_cn
    FROM truth_vault.v_paid_boost_events
),
au AS MATERIALIZED (
    SELECT a.row_id AS note_id, a.audit_id, a.occurred_at, a.operation, a.changed_cols,
           (a.occurred_at + interval '8 hours')::date AS cn_day,
           ((a.operation = 'UPDATE' AND a.changed_cols ? 'last_seen_run_id')
            OR (a.operation = 'INSERT' AND a.changed_cols ->> 'last_seen_run_id' IS NOT NULL)) AS full_sync
    FROM truth_vault.audit_log a
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes'
      AND a.operation IN ('INSERT', 'UPDATE')
      AND a.row_id IN (SELECT note_id FROM ev)
),
first_au AS (
    SELECT note_id, min(cn_day) AS first_cn_day,
           min(occurred_at) FILTER (WHERE full_sync) AS first_stamp_at
    FROM au GROUP BY note_id
),
obs AS MATERIALIZED (
    SELECT DISTINCT ON (x.note_id, x.cn_day) x.note_id, x.cn_day, x.occurred_at AS t_obs, x.kind
    FROM (
        SELECT note_id, cn_day, occurred_at, audit_id, 'full_sync'::text AS kind FROM au WHERE full_sync
        UNION ALL
        SELECT a.note_id, a.cn_day, a.occurred_at, a.audit_id, 'pre_v1_9_any_write'
        FROM au a JOIN first_au f ON f.note_id = a.note_id
        WHERE NOT a.full_sync
          AND a.occurred_at < LEAST(f.first_stamp_at, timestamp '2026-08-31 00:00')
    ) x
    ORDER BY x.note_id, x.cn_day, (x.kind = 'full_sync') DESC, x.occurred_at DESC, x.audit_id DESC
),
vals AS MATERIALIZED (
    SELECT au.note_id, au.audit_id, au.occurred_at, au.cn_day, v.item, v.old_v, v.new_v
    FROM au
    CROSS JOIN LATERAL (
        SELECT t.item,
               CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> t.item -> 0 END AS old_v,
               CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> t.item -> 1
                    ELSE au.changed_cols -> t.item END AS new_v
        FROM (VALUES ('comments_count'), ('impressions'), ('reads'), ('interactions'),
                     ('tier'), ('tier_source')) AS t(item)
        WHERE au.changed_cols ? t.item
        UNION ALL
        SELECT r.item, r.old_v, r.new_v
        FROM (SELECT CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> 'raw_extra' -> 0 END AS ob,
                     CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> 'raw_extra' -> 1
                          ELSE au.changed_cols -> 'raw_extra' END AS nb) b
        CROSS JOIN LATERAL (VALUES
            ('raw:实时数据.评论数',
             truth_vault.tv_raw_cell(b.ob, '实时数据.评论数'), truth_vault.tv_raw_cell(b.nb, '实时数据.评论数')),
            ('raw:最近检查时间',
             truth_vault.tv_raw_cell(b.ob, '最近检查时间'), truth_vault.tv_raw_cell(b.nb, '最近检查时间')),
            ('raw:相关截图.file_token',
             (SELECT jsonb_agg(DISTINCT tok ORDER BY tok)
              FROM jsonb_array_elements_text(jsonb_path_query_array(truth_vault.tv_raw_cell(b.ob, '相关截图'),
                                                                    'lax $[*].file_token')) AS tok),
             (SELECT jsonb_agg(DISTINCT tok ORDER BY tok)
              FROM jsonb_array_elements_text(jsonb_path_query_array(truth_vault.tv_raw_cell(b.nb, '相关截图'),
                                                                    'lax $[*].file_token')) AS tok))
        ) AS r(item, old_v, new_v)
        WHERE au.changed_cols ? 'raw_extra'
          AND (au.operation = 'INSERT' OR r.old_v IS DISTINCT FROM r.new_v)
    ) v
),
base_obs AS (
    SELECT DISTINCT ON (e.event_id) e.event_id, ob.t_obs, ob.cn_day, ob.kind
    FROM ev e
    JOIN obs ob ON ob.note_id = e.note_id AND ob.cn_day < e.boost_date
    ORDER BY e.event_id, ob.cn_day DESC
),
slot AS (
    SELECT e.event_id, e.note_id, e.boost_date, e.d0_utc, e.today_cn, k.k,
           CASE WHEN k.k >= 0 THEN e.boost_date + k.k END AS target_cn_day,
           coalesce(bo.t_obs, ob.t_obs) AS t_obs,
           coalesce(bo.cn_day, ob.cn_day) AS obs_cn_day,
           coalesce(bo.kind, ob.kind) AS obs_kind,
           f.first_cn_day
    FROM ev e
    CROSS JOIN (VALUES (-1), (0), (1), (3), (7)) AS k(k)
    LEFT JOIN first_au f ON f.note_id = e.note_id
    LEFT JOIN base_obs bo ON k.k = -1 AND bo.event_id = e.event_id
    LEFT JOIN obs ob ON k.k >= 0 AND ob.note_id = e.note_id AND ob.cn_day = e.boost_date + k.k
),
slot2 AS MATERIALIZED (
    SELECT s.*,
           CASE
               WHEN s.k >= 0 AND (s.target_cn_day > s.today_cn OR (s.target_cn_day = s.today_cn AND s.t_obs IS NULL))
                   THEN 'missing:not_due'
               WHEN s.t_obs IS NOT NULL THEN 'ok'
               WHEN s.k = -1 AND (s.first_cn_day IS NULL OR s.first_cn_day >= s.boost_date) THEN 'missing:before_history'
               WHEN s.k = -1 THEN 'missing:no_reading_before_boost'
               WHEN s.first_cn_day IS NULL OR s.first_cn_day > s.target_cn_day THEN 'missing:before_history'
               ELSE 'missing:no_full_sync_that_day'
           END AS slot_status
    FROM slot s
),
-- 每格每项: 读的那一刻之前最后一次改 (lv); 那之前 audit 里没改过 → 之后第一次改的旧值 (fv)
lv AS MATERIALIZED (
    SELECT DISTINCT ON (s.event_id, s.k, va.item)
           s.event_id, s.k, va.item, va.new_v, va.occurred_at, va.cn_day
    FROM slot2 s
    JOIN vals va ON va.note_id = s.note_id AND va.occurred_at <= s.t_obs
    ORDER BY s.event_id, s.k, va.item, va.occurred_at DESC, va.audit_id DESC
),
fv AS (
    SELECT DISTINCT ON (s.event_id, s.k, va.item)
           s.event_id, s.k, va.item, va.old_v
    FROM slot2 s
    JOIN vals va ON va.note_id = s.note_id AND va.occurred_at > s.t_obs
    ORDER BY s.event_id, s.k, va.item, va.occurred_at, va.audit_id
),
sv AS (
    SELECT event_id, k, item, new_v AS v, occurred_at AS changed_at, cn_day AS changed_cn_day FROM lv
    UNION ALL
    SELECT fv.event_id, fv.k, fv.item, fv.old_v, NULL::timestamp, NULL::date
    FROM fv
    WHERE NOT EXISTS (SELECT 1 FROM lv WHERE lv.event_id = fv.event_id AND lv.k = fv.k AND lv.item = fv.item)
),
piv AS (
    SELECT s.event_id, s.note_id, s.boost_date, s.d0_utc, s.k, s.target_cn_day, s.obs_cn_day, s.t_obs, s.obs_kind,
           s.slot_status,
           max(sv.v::text) FILTER (WHERE sv.item = 'comments_count')::jsonb           AS cc_typed,
           max(sv.v::text) FILTER (WHERE sv.item = 'raw:实时数据.评论数')::jsonb       AS cc_raw,
           max(sv.v::text) FILTER (WHERE sv.item = 'raw:最近检查时间')::jsonb          AS measured_raw,
           max(sv.v::text) FILTER (WHERE sv.item = 'impressions')::jsonb              AS imp_v,
           max(sv.changed_at) FILTER (WHERE sv.item = 'impressions')                  AS imp_at,
           max(sv.changed_cn_day) FILTER (WHERE sv.item = 'impressions')              AS imp_day,
           max(sv.v::text) FILTER (WHERE sv.item = 'reads')::jsonb                    AS rd_v,
           max(sv.changed_at) FILTER (WHERE sv.item = 'reads')                        AS rd_at,
           max(sv.changed_cn_day) FILTER (WHERE sv.item = 'reads')                    AS rd_day,
           max(sv.v::text) FILTER (WHERE sv.item = 'interactions')::jsonb             AS it_v,
           max(sv.changed_at) FILTER (WHERE sv.item = 'interactions')                 AS it_at,
           max(sv.changed_cn_day) FILTER (WHERE sv.item = 'interactions')             AS it_day,
           max(sv.v::text) FILTER (WHERE sv.item = 'raw:相关截图.file_token')::jsonb   AS shot_v,
           max(sv.changed_at) FILTER (WHERE sv.item = 'raw:相关截图.file_token')       AS shot_at,
           max(sv.changed_cn_day) FILTER (WHERE sv.item = 'raw:相关截图.file_token')   AS shot_day,
           max(sv.v #>> '{}') FILTER (WHERE sv.item = 'tier')                         AS tier,
           max(sv.v #>> '{}') FILTER (WHERE sv.item = 'tier_source')                  AS tier_source
    FROM slot2 s
    LEFT JOIN sv ON sv.event_id = s.event_id AND sv.k = s.k
    GROUP BY s.event_id, s.note_id, s.boost_date, s.d0_utc, s.k, s.target_cn_day, s.obs_cn_day, s.t_obs,
             s.obs_kind, s.slot_status
),
num AS (
    SELECT p.*,
           CASE WHEN p.cc_typed IS NOT NULL AND jsonb_typeof(p.cc_typed) <> 'null' THEN p.cc_typed
                WHEN p.obs_cn_day < date '2026-09-18' AND p.cc_raw IS NOT NULL AND jsonb_typeof(p.cc_raw) <> 'null'
                    THEN p.cc_raw END AS cc_v,
           CASE WHEN p.cc_typed IS NOT NULL AND jsonb_typeof(p.cc_typed) <> 'null' THEN 'comments_count'
                WHEN p.obs_cn_day < date '2026-09-18' AND p.cc_raw IS NOT NULL AND jsonb_typeof(p.cc_raw) <> 'null'
                    THEN 'raw_extra:实时数据.评论数' END AS cc_src,
           (p.k >= 0 AND (p.shot_at IS NOT NULL AND p.shot_at >= p.d0_utc)) AS shot_fresh
    FROM piv p
),
fin AS (
    SELECT n.*,
           CASE WHEN jsonb_typeof(n.cc_v) = 'number' THEN (n.cc_v #>> '{}')::numeric
                WHEN jsonb_typeof(n.cc_v) = 'string' AND n.cc_v #>> '{}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (n.cc_v #>> '{}')::numeric
           END AS cc_num,
           CASE WHEN jsonb_typeof(n.imp_v) = 'number' THEN (n.imp_v #>> '{}')::numeric END AS imp_num,
           CASE WHEN jsonb_typeof(n.rd_v) = 'number' THEN (n.rd_v #>> '{}')::numeric END AS rd_num,
           CASE WHEN jsonb_typeof(n.it_v) = 'number' THEN (n.it_v #>> '{}')::numeric END AS it_num
    FROM num n
)
SELECT f.event_id, f.note_id, f.boost_date, f.k,
       CASE f.k WHEN -1 THEN 'baseline' WHEN 0 THEN 'boost_day_order_unknown' ELSE 'd+' || f.k END AS slot_label,
       f.target_cn_day, f.obs_cn_day, f.t_obs AS obs_at_utc, f.obs_kind, f.slot_status,
       -- 评论数
       CASE WHEN f.slot_status = 'ok' THEN f.cc_num END AS comments,
       CASE WHEN f.slot_status <> 'ok' THEN f.slot_status
            WHEN f.cc_v IS NULL THEN 'missing:value_null'
            WHEN f.cc_num IS NULL THEN 'missing:value_not_numeric'
            ELSE 'ok' END AS comments_status,
       CASE WHEN f.slot_status = 'ok' AND f.cc_num IS NOT NULL THEN f.cc_src END AS comments_source,
       CASE WHEN f.slot_status = 'ok' AND jsonb_typeof(f.measured_raw) = 'number'
             AND (f.measured_raw #>> '{}')::numeric BETWEEN 946684800000 AND 4102444800000
            THEN (to_timestamp(((f.measured_raw #>> '{}')::numeric / 1000.0)::double precision) AT TIME ZONE 'Asia/Shanghai')
       END AS comments_measured_at_cn,
       -- 曝光 / 阅读 / 互动 (k ≥ 0 要求投流日之后改过或换过截图)
       CASE WHEN f.slot_status = 'ok' AND f.imp_num IS NOT NULL
             AND (f.k = -1 OR f.shot_fresh OR f.imp_at >= f.d0_utc) THEN f.imp_num END AS impressions,
       CASE WHEN f.slot_status <> 'ok' THEN f.slot_status
            WHEN f.imp_num IS NULL THEN 'missing:value_null'
            WHEN f.k >= 0 AND NOT (f.shot_fresh OR coalesce(f.imp_at >= f.d0_utc, false)) THEN 'missing:no_rescreenshot'
            ELSE 'ok' END AS impressions_status,
       CASE WHEN f.slot_status = 'ok' THEN f.imp_day END AS impressions_changed_cn_day,
       CASE WHEN f.slot_status = 'ok' AND f.rd_num IS NOT NULL
             AND (f.k = -1 OR f.shot_fresh OR f.rd_at >= f.d0_utc) THEN f.rd_num END AS reads,
       CASE WHEN f.slot_status <> 'ok' THEN f.slot_status
            WHEN f.rd_num IS NULL THEN 'missing:value_null'
            WHEN f.k >= 0 AND NOT (f.shot_fresh OR coalesce(f.rd_at >= f.d0_utc, false)) THEN 'missing:no_rescreenshot'
            ELSE 'ok' END AS reads_status,
       CASE WHEN f.slot_status = 'ok' THEN f.rd_day END AS reads_changed_cn_day,
       CASE WHEN f.slot_status = 'ok' AND f.it_num IS NOT NULL
             AND (f.k = -1 OR f.shot_fresh OR f.it_at >= f.d0_utc) THEN f.it_num END AS interactions,
       CASE WHEN f.slot_status <> 'ok' THEN f.slot_status
            WHEN f.it_num IS NULL THEN 'missing:value_null'
            WHEN f.k >= 0 AND NOT (f.shot_fresh OR coalesce(f.it_at >= f.d0_utc, false)) THEN 'missing:no_rescreenshot'
            ELSE 'ok' END AS interactions_status,
       CASE WHEN f.slot_status = 'ok' THEN f.it_day END AS interactions_changed_cn_day,
       -- 截图: 这次读时的 file_token 集合里, 基线那次没有的
       CASE WHEN f.slot_status = 'ok' THEN f.shot_day END AS screenshot_changed_cn_day,
       CASE WHEN f.slot_status = 'ok' AND f.k >= 0 THEN
           (SELECT jsonb_agg(t.tok ORDER BY t.tok)
            FROM jsonb_array_elements_text(coalesce(f.shot_v, '[]'::jsonb)) AS t(tok)
            WHERE NOT coalesce(b.shot_v, '[]'::jsonb) ? t.tok)
       END AS screenshot_tokens_new,
       CASE WHEN f.slot_status = 'ok' THEN f.tier END AS tier,
       CASE WHEN f.slot_status = 'ok' THEN f.tier_source END AS tier_source
FROM fin f
LEFT JOIN fin b ON b.event_id = f.event_id AND b.k = -1 AND b.slot_status = 'ok';

COMMENT ON VIEW truth_vault.v_paid_boost_readings IS
    '投流证据链 F2 (D-133): 每个投流事件 × k (-1 基线 = 投流日之前最后一次完整同步, 0 = 投流当天、前后不明, 1/3/7 = 正好那天) 一行, '
    '全部从 audit_log 读。missing:<原因> 的值一律 NULL, 从不写 0; 曝光类 k≥0 要投流日之后改过或换过截图才给值。';


-- ════════════════════════════════════════════════════════════════════
-- 视图 5 · v_paid_boost_evidence: 一个事件一行的宽表 (人看 / 读数报告用); F4 以后往这里加干净样本列
-- ════════════════════════════════════════════════════════════════════
--   增量只在两头都是 ok 时才算, 否则 NULL + 状态说缺哪头。ops_* 一块放最后, 不进任何增量。
CREATE OR REPLACE VIEW truth_vault.v_paid_boost_evidence AS
WITH r AS (
    SELECT * FROM truth_vault.v_paid_boost_readings
),
p AS (
    SELECT event_id,
           max(obs_cn_day) FILTER (WHERE k = -1)                AS base_cn_day,
           max(obs_kind) FILTER (WHERE k = -1)                   AS base_obs_kind,
           max(comments) FILTER (WHERE k = -1)                   AS comments_base,
           max(comments_status) FILTER (WHERE k = -1)            AS comments_base_status,
           max(comments_source) FILTER (WHERE k = -1)            AS comments_base_source,
           max(comments) FILTER (WHERE k = 0)                    AS comments_d0,
           max(comments_status) FILTER (WHERE k = 0)             AS comments_d0_status,
           max(comments) FILTER (WHERE k = 1)                    AS comments_d1,
           max(comments_status) FILTER (WHERE k = 1)             AS comments_d1_status,
           max(comments) FILTER (WHERE k = 3)                    AS comments_d3,
           max(comments_status) FILTER (WHERE k = 3)             AS comments_d3_status,
           max(comments) FILTER (WHERE k = 7)                    AS comments_d7,
           max(comments_status) FILTER (WHERE k = 7)             AS comments_d7_status,
           max(impressions) FILTER (WHERE k = -1)                AS impressions_base,
           max(impressions_status) FILTER (WHERE k = -1)         AS impressions_base_status,
           max(impressions_changed_cn_day) FILTER (WHERE k = -1) AS impressions_base_changed_cn_day,
           max(impressions) FILTER (WHERE k = 7)                 AS impressions_d7,
           max(impressions_status) FILTER (WHERE k = 7)          AS impressions_d7_status,
           max(reads) FILTER (WHERE k = -1)                      AS reads_base,
           max(reads_status) FILTER (WHERE k = -1)               AS reads_base_status,
           max(reads) FILTER (WHERE k = 7)                       AS reads_d7,
           max(reads_status) FILTER (WHERE k = 7)                AS reads_d7_status,
           max(interactions) FILTER (WHERE k = -1)               AS interactions_base,
           max(interactions_status) FILTER (WHERE k = -1)        AS interactions_base_status,
           max(interactions) FILTER (WHERE k = 7)                AS interactions_d7,
           max(interactions_status) FILTER (WHERE k = 7)         AS interactions_d7_status,
           max(screenshot_tokens_new::text) FILTER (WHERE k = 7)::jsonb AS screenshot_tokens_new_d7,
           max(tier) FILTER (WHERE k = -1)                       AS tier_base,
           max(tier) FILTER (WHERE k = 0)                        AS tier_d0,
           max(tier) FILTER (WHERE k = 7)                        AS tier_d7
    FROM r
    GROUP BY event_id
)
SELECT e.event_id, e.note_id, e.project_id, e.boost_date, e.date_sources, e.marker_cols, e.marker_raw,
       e.publish_cn_date, e.days_after_publish, e.paid_promoted_state, e.vanished,
       e.takeoff_cn_date, e.takeoff_vs_window,
       e.comment_maintained_seeded,
       p.base_cn_day, p.base_obs_kind,
       p.comments_base, p.comments_base_status, p.comments_base_source,
       p.comments_d0, p.comments_d0_status,
       p.comments_d1, p.comments_d1_status,
       p.comments_d3, p.comments_d3_status,
       p.comments_d7, p.comments_d7_status,
       CASE WHEN p.comments_base_status = 'ok' AND p.comments_d1_status = 'ok' THEN p.comments_d1 - p.comments_base END AS comments_delta_d1,
       CASE WHEN p.comments_base_status <> 'ok' THEN 'base:' || p.comments_base_status
            WHEN p.comments_d1_status <> 'ok' THEN 'd1:' || p.comments_d1_status ELSE 'ok' END AS comments_delta_d1_status,
       CASE WHEN p.comments_base_status = 'ok' AND p.comments_d3_status = 'ok' THEN p.comments_d3 - p.comments_base END AS comments_delta_d3,
       CASE WHEN p.comments_base_status <> 'ok' THEN 'base:' || p.comments_base_status
            WHEN p.comments_d3_status <> 'ok' THEN 'd3:' || p.comments_d3_status ELSE 'ok' END AS comments_delta_d3_status,
       CASE WHEN p.comments_base_status = 'ok' AND p.comments_d7_status = 'ok' THEN p.comments_d7 - p.comments_base END AS comments_delta_d7,
       CASE WHEN p.comments_base_status <> 'ok' THEN 'base:' || p.comments_base_status
            WHEN p.comments_d7_status <> 'ok' THEN 'd7:' || p.comments_d7_status ELSE 'ok' END AS comments_delta_d7_status,
       p.impressions_base, p.impressions_base_status, p.impressions_base_changed_cn_day,
       p.impressions_d7, p.impressions_d7_status,
       p.reads_base, p.reads_base_status, p.reads_d7, p.reads_d7_status,
       p.interactions_base, p.interactions_base_status, p.interactions_d7, p.interactions_d7_status,
       p.screenshot_tokens_new_d7,
       p.tier_base, p.tier_d0, p.tier_d7,
       coalesce(p.tier_d0, p.tier_base) AS tier_on_boost_day,
       CASE WHEN p.tier_d0 IS NOT NULL THEN 'k=0' WHEN p.tier_base IS NOT NULL THEN 'k=-1 (投流当天没读到)' END AS tier_on_boost_day_src,
       -- ops_* 一块: 运营自报, 不进增量
       e.ops_effect_raw, e.ops_effect_value, e.ops_effect_metric_flag, e.ops_effect_vs_current_impressions
FROM truth_vault.v_paid_boost_events e
LEFT JOIN p ON p.event_id = e.event_id;

COMMENT ON VIEW truth_vault.v_paid_boost_evidence IS
    '投流证据链 (D-133): 一个投流事件一行。评论数 基线 / 当天 / D+1 / D+3 / D+7 各带状态, 增量只在两头都 ok 时算; '
    '曝光类给基线和 D+7; tier 给基线 / 当天 / D+7。ops_* 是运营自报, 单列, 不进增量。逐例证据, 不做因果结论。';
