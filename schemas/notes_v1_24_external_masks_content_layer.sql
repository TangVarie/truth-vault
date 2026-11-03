-- truth_vault v1.24 · 外部参考卡的品牌名遮挡表 external_note_masks + 我们自己帖子的内容层 notes.content_layer (D-140, 2026-11-03)
-- ════════════════════════════════════════════════════════════════════
-- 治的是什么:
--   ① 外部参考书架 (librarian/external.py) 以前只收 Jev 分诊判了「没带产品」(has_product = false) 的外部帖, 用它代替
--      「正文里没有别家品牌名」(D-117)。这个代替不成立: 分诊只看标题 + 约 60 字摘要, 11-03 只读 994 篇「没带产品」里
--      482 篇正文点了产品; 上架的卡把没遮的别家品牌名原样带进写作台。owner 11-03:「直接判断就好了吧, 判断哪些属于
--      产品名, 哪些属于内容, 我们要学的不就是内容的写法吗」。改成: 模型只【列出】每篇里的品牌 / 产品名 (逐字), 代码
--      核过这些词真在原文里, 再替换成「某品牌」/「某产品」—— 模型从不改写正文, 别的字一个不动。列出来的词存在
--      external_note_masks, 一篇一行; text_sha 是列词那一刻的「标题 + 换行 + 正文」的 sha256, 正文变了就重列。
--   ② 我们自己的帖分四层 (owner 方法论): P 产品贴 / T 流量贴 / Q 提问贴 / J 精品贴。飞书「方向」列有的项目写着这几个词
--      (raw_extra._direction_raw), 老项目只有 notes.intent (traffic / conversion)。notes.content_layer 存算出来的层,
--      规则在 scripts/_common.derive_layer (mapping 写明的 layer → 严格词规则 → intent → NULL), 写作台按卡要层时用它。
--
-- 这份迁移做两件事 (都是加, 不改已有的行为):
--   ① 表 truth_vault.external_note_masks:
--        note_id    外部帖 id, 主键, 外键到 external_notes(note_id) ON DELETE CASCADE (external_notes.note_id 是主键, 11-03 核过;
--                   Jev 的 apply_rows 是 upsert, 不删行, 级联只在真删帖时起作用)
--        terms      [{"t": "<原文里逐字出现的词>", "k": "品牌" | "产品"}, …]; 空数组 = 查过了、没有要遮的
--        text_sha   sha256(title + '\n' + body), 列词时的那份原文; 和现在的原文对不上 = 过期, 馆员当它没有, 夜跑重列
--        model      列词的模型 (MASK_MODEL, 默认 claude-haiku-5-5)
--        masked_at  列词时刻
--      写入方只有 scripts/mask_external_names.py (daily-sync advisory 步); 读的是馆员 (librarian/external.py)。
--   ② 列 truth_vault.notes.content_layer TEXT NULL, CHECK 只许 P / T / Q / J (NULL = 算不出, 不猜)。
--      写入方: feishu → TV 同步 (每行都带, 每晚整行重写) 和 scripts/backfill_content_layer.py (只往空里填)。
--      essence / 策展 / 通道 1 都不碰这一列 (CI 守着 essence 的写回)。
--
-- 回填 (不在这份 SQL 里做, 因为规则要读 mappings/*.yaml):
--   · daily 项目: feishu → TV 那一步每晚把飞书里每一行整行重写 (transform_row 每行都带 content_layer), 跑完这份迁移的
--     下一晚就自己填满了。飞书里已经删掉的行不再被重写, 留空 (它们本来就被消费方排除, v_notes_vanished)。
--   · on_demand 项目 (HXZ_FB / HXZ_QD / NRT_phase2 / NRT_phase3 / NUC_phase1 / TGV_phase1 / TXQ_phase1): 夜跑不同步它们,
--     daily-sync 的「内容层补填」advisory 步 (backfill_content_layer.py) 同一晚按库里的方向原值和 intent 填。
--     这一步每篇写一次 UPDATE, 会进 audit_log (11-03 只读预演: 2,104 篇, 一次性); 之后每晚 0 行。
--   · 11-03 只读预演 (同一个 derive_layer 跑在库里的方向原值 + intent 上, 全库 6,914 篇): P 1,092 · T 2,563 · Q 532 · J 3 ·
--     算不出 (NULL) 2,724; 分项目见 DECISIONS D-140。
-- 外部遮挡的回填: mask_external_names.py 每晚最多 1,500 篇 (--limit), 第一晚把现有约 1,419 篇全列一遍 (Haiku 级模型,
--   按标价约 0.1–0.2 美元); 之后每晚只列新进的、正文变过的。
--
-- 代码是宽容的 (owner 没跑这份之前什么都不能坏):
--   · 没有 external_note_masks: 馆员把每篇外部帖都当没遮过 —— 卡上只给结构、不给原文摘录, 也不强塞外部卡; 打一行 warning。
--     mask 脚本 rc=2 (判不了), 不写。
--   · 没有 notes.content_layer: sync 这一轮不写这一列 (别的照旧, 一行 warning); 补填脚本 rc=2 不写。
--   · 两样都故意不进 _common._REQUIRED_COLUMNS, 免得迁移没跑之前 sync 先红。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次 (合并之前或合并当天), 可以重跑 (IF NOT EXISTS; CHECK 先 DROP IF EXISTS
--   再加)。加一个可空列不重写 notes 表, 不锁很久。跑完看最后那行 SELECT (masks 0 行、content_layer 全空 = 对的, 当晚夜跑开始填)。
-- 权限: 两样都在 truth_vault 里, RLS 打开、不加 policy (anon / authenticated 读写都不行); service_role 照常读写
--   (同 notes_v1_2 的默认授权; 这里再显式 GRANT / REVOKE 一遍, 不依赖默认权限有没有被改过)。
-- 在 notes_v1_18 (external_notes) 之后应用。
-- ════════════════════════════════════════════════════════════════════


-- ── ① 外部帖的品牌 / 产品名遮挡表 ──────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.external_note_masks (
    note_id    TEXT PRIMARY KEY REFERENCES truth_vault.external_notes (note_id) ON DELETE CASCADE,
    terms      JSONB NOT NULL DEFAULT '[]'::jsonb,
    text_sha   TEXT NOT NULL,
    model      TEXT,
    masked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE truth_vault.external_note_masks DROP CONSTRAINT IF EXISTS external_note_masks_terms_is_array;
ALTER TABLE truth_vault.external_note_masks
    ADD CONSTRAINT external_note_masks_terms_is_array CHECK (jsonb_typeof(terms) = 'array');

COMMENT ON TABLE truth_vault.external_note_masks IS
    '外部帖里要遮的品牌 / 产品名 (D-140): 模型只列词、代码核过逐字出现才存; 馆员上架时按 text_sha 核对原文没变再替换成 某品牌 / 某产品。'
    '写入方: scripts/mask_external_names.py。';
COMMENT ON COLUMN truth_vault.external_note_masks.terms IS
    '[{"t": 原文里逐字出现的词, "k": "品牌" | "产品"}]; 空数组 = 查过了、没有要遮的。';
COMMENT ON COLUMN truth_vault.external_note_masks.text_sha IS
    'sha256(coalesce(title, '''') || E''\n'' || coalesce(body, '''')) —— 列词时的那份原文; 和现在对不上 = 过期, 当没有。';

ALTER TABLE truth_vault.external_note_masks ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE truth_vault.external_note_masks FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE truth_vault.external_note_masks TO service_role';
    END IF;
END $$;


-- ── ② 我们自己帖子的内容层 ─────────────────────────────────────────
ALTER TABLE truth_vault.notes
    ADD COLUMN IF NOT EXISTS content_layer TEXT;

ALTER TABLE truth_vault.notes DROP CONSTRAINT IF EXISTS notes_content_layer_check;
ALTER TABLE truth_vault.notes
    ADD CONSTRAINT notes_content_layer_check CHECK (content_layer IN ('P', 'T', 'Q', 'J'));

COMMENT ON COLUMN truth_vault.notes.content_layer IS
    '内容层 (D-140): P 产品贴 / T 流量贴 / Q 提问贴 / J 精品贴; NULL = 算不出。规则 scripts/_common.derive_layer '
    '(mapping 写明的 layer → 严格词规则 → intent → NULL); 写入方 feishu 同步与 backfill_content_layer.py, essence 不碰。';


-- ── 跑完看这一行 ───────────────────────────────────────────────────
--   刚跑完: masks 0、content_layer 有值 0 (当晚夜跑开始填)。重跑: 两个数是夜跑填进去的, 不会被这份迁移清掉。
SELECT (SELECT count(*) FROM truth_vault.external_note_masks)                        AS masks_rows,
       (SELECT count(*) FROM truth_vault.external_notes)                             AS external_notes,
       (SELECT count(*) FROM truth_vault.notes WHERE content_layer IS NOT NULL)      AS notes_with_layer,
       (SELECT count(*) FROM truth_vault.notes)                                      AS notes_total;
