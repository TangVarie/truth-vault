-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/009_deskcore.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-08-22 · D-041 写作台内核外置 (deskcore MCP 服务)
--
-- 背景:
--   autowriter 的 Streamlit 界面停用, 但它 Supabase 里的积累 (40 项目 /
--   269 条记忆 / 103 条已确认负例 / 调校笔记) 是几年下来最值钱的资产.
--   deskcore/ 把这些能力做成 MCP 工具, 挂到 WorkBuddy / Claude Code /
--   CodeBuddy. 本 migration 只【补齐】外置后缺的三张表 + 一列,
--   现有 8 张 autowriter 表【一行不动】.
--
-- 为什么需要这三张表 (每张对应一个已确诊的根因, 见 docs/27):
--
--   angle_ledger      ← 根因: 跨批次没有"哪些角度组合用过"的持久记录.
--                       autowriter 的 _assign_slot_coordinates(generator.py:1301)
--                       被移除成死代码, 且它本来也只在单批内去重.
--
--   draft_fingerprints ← 根因: 查重池 queue_embeddings 是 worker 进程内的
--                       内存字典 (app.py:1024), 进程重启即清空; 且只比标题.
--                       本表是持久、全量、跨人、跨批次的查重底座.
--
--   style_edits       ← 手动精修 diff 的原始存放处. 笔记是导出物, diff 才是事实,
--                       换蒸馏 prompt 时要能重算.
--
--   user_calibration_notes ← 根因: projects.calibration_notes 是项目级单份,
--                       无法承载"项目规则共享 + 个人风格私有"的分层.
--                       项目级那份保留为共享基线, 本表是个人叠加层.
--
-- 一列:
--   items.updated_at  ← scripts/sync_autowriter_decisions_to_prepublish.py:36-40
--                       记过: items 没有 updated_at, 只能按 created_at 过滤,
--                       导致迟到的人工决策漏收 (--since-days 从 90 改 365 是补丁).
--
-- 隔离口径 (用户 2026-08-22 拍板):
--   共享 (按 project_id): memories / projects prompt 包 / angle_ledger /
--                         draft_fingerprints
--   私有 (按 user_id):    user_calibration_notes / items.example_label 正负例
--
-- RLS: 全部 enable 但不建 policy = service_role only, 与 truth_vault 现有
--      15 张后台表同模式 (deskcore 服务端持 service_role, 自己执行隔离口径).
--
-- 部署:
--   Supabase SQL Editor 粘贴执行, 或 MCP apply_migration.
--   建议先在 branch 库跑一遍 + get_advisors 核验无回归再进 prod.
--
-- 幂等: 重复执行不报错 (IF NOT EXISTS 全覆盖).
--
-- 回滚:
--   DROP TABLE IF EXISTS autowriter.draft_fingerprints CASCADE;
--   DROP TABLE IF EXISTS autowriter.angle_ledger CASCADE;
--   DROP TABLE IF EXISTS autowriter.user_calibration_notes CASCADE;
--   DROP TABLE IF EXISTS autowriter.style_edits CASCADE;
--   ALTER TABLE autowriter.items DROP COLUMN IF EXISTS updated_at;
--   DROP FUNCTION IF EXISTS autowriter._deskcore_touch_updated_at();
-- ════════════════════════════════════════════════════════════════════

BEGIN;

SET LOCAL search_path TO autowriter, extensions, public;

-- ── 0. 共用 updated_at 触发器函数 ────────────────────────────────────
-- DEFAULT 只在 INSERT 生效; upsert 的 DO UPDATE 分支必须靠触发器刷新,
-- 否则下游按 updated_at 做增量/失效判断会漏 (同 notes_v1_4 的教训).
CREATE OR REPLACE FUNCTION autowriter._deskcore_touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- ── 1. angle_ledger · 发牌台账 (共享) ────────────────────────────────
-- 一行 = 一次发牌抽出的一个角度组合.
-- angle_key 是 dims 的规范化指纹 (deskcore/core.py:angle_key 生成),
-- 用它做"这个组合最近用过没有"的判断, 而不是比 JSONB.
CREATE TABLE IF NOT EXISTS autowriter.angle_ledger (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id          UUID NOT NULL REFERENCES autowriter.projects(id) ON DELETE CASCADE,
    angle_key           TEXT NOT NULL,
    dims                JSONB NOT NULL DEFAULT '{}'::jsonb,
    drawn_by            UUID,
    drawn_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- NULL = 抽了但没写成稿 (占位会过期, 见 deskcore 的 avoid_days 语义);
    -- 非 NULL = 真的产出了稿子, 是"用掉了"的强证据.
    consumed_version_id UUID,
    consumed_at         TIMESTAMPTZ
);

COMMENT ON TABLE autowriter.angle_ledger IS
    'deskcore 发牌台账: 记录每个项目抽过哪些角度组合, 供 draw_angles 跨批次避重. D-041.';
COMMENT ON COLUMN autowriter.angle_ledger.angle_key IS
    'dims 的规范化指纹(排序后 join). 避重比对用它, 不比 JSONB.';
COMMENT ON COLUMN autowriter.angle_ledger.consumed_version_id IS
    'NULL=抽了未用(占位, 按时间自然过期); 非 NULL=已产出成稿, 强避重证据.';

CREATE INDEX IF NOT EXISTS angle_ledger_project_key_idx
    ON autowriter.angle_ledger (project_id, angle_key);
CREATE INDEX IF NOT EXISTS angle_ledger_project_drawn_idx
    ON autowriter.angle_ledger (project_id, drawn_at DESC);

ALTER TABLE autowriter.angle_ledger ENABLE ROW LEVEL SECURITY;

-- ── 2. draft_fingerprints · 成稿指纹库 (共享) ────────────────────────
-- 替代 autowriter 内存态 queue_embeddings(app.py:1024) 的持久版本.
-- 三种指纹各挡一类重复:
--   title_embedding  → 同角度换说法的标题 (语义)
--   opening_hash     → 正文前 N 字切入方式雷同 (确定性, 最省)
--   ngram_hashes     → 跨篇高频四字串 (对齐 human-writing/check_prose.py 的跨篇指纹)
CREATE TABLE IF NOT EXISTS autowriter.draft_fingerprints (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID NOT NULL REFERENCES autowriter.projects(id) ON DELETE CASCADE,
    version_id      UUID,
    user_id         UUID,
    title           TEXT NOT NULL DEFAULT '',
    opening         TEXT NOT NULL DEFAULT '',
    title_embedding vector(768),
    opening_hash    TEXT,
    ngram_hashes    TEXT[] NOT NULL DEFAULT '{}',
    angle_key       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE autowriter.draft_fingerprints IS
    'deskcore 成稿指纹库: 持久/全量/跨人/跨批次查重底座. 取代 autowriter 内存态 queue_embeddings. D-041.';
COMMENT ON COLUMN autowriter.draft_fingerprints.title_embedding IS
    'Gemini text-embedding-004 768d, 与 autowriter.versions.embedding 同一模型, 可互比.';
COMMENT ON COLUMN autowriter.draft_fingerprints.opening_hash IS
    '正文首个非空行前 25 字规范化后的 sha256 前 16 位. 确定性精确撞车检测.';
COMMENT ON COLUMN autowriter.draft_fingerprints.ngram_hashes IS
    '正文四字串 shingle 的 hash 采样. 跨篇模板化检测(同 check_prose.py 的 four_grams).';

CREATE INDEX IF NOT EXISTS draft_fp_project_created_idx
    ON autowriter.draft_fingerprints (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS draft_fp_opening_hash_idx
    ON autowriter.draft_fingerprints (project_id, opening_hash)
    WHERE opening_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS draft_fp_ngram_gin_idx
    ON autowriter.draft_fingerprints USING GIN (ngram_hashes);
-- 向量索引: ivfflat 与 versions_embedding_idx 同款(cosine).
-- lists=100 是 autowriter 现有约定; 库小于 ~1k 行时 planner 可能仍走顺序扫, 正常.
CREATE INDEX IF NOT EXISTS draft_fp_embedding_idx
    ON autowriter.draft_fingerprints USING ivfflat (title_embedding vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE autowriter.draft_fingerprints ENABLE ROW LEVEL SECURITY;

-- ── 3. user_calibration_notes · 个人调校笔记 (私有) ──────────────────
-- projects.calibration_notes 保留为【项目级共享基线】, 本表是【个人叠加层】.
-- deskcore 注入 P1 时的顺序是: 项目基线 → 个人叠加 (个人在后, 冲突时更近).
CREATE TABLE IF NOT EXISTS autowriter.user_calibration_notes (
    project_id  UUID NOT NULL REFERENCES autowriter.projects(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, user_id)
);

COMMENT ON TABLE autowriter.user_calibration_notes IS
    'deskcore 个人调校笔记(私有层). 项目级共享基线仍在 projects.calibration_notes. D-041.';

DROP TRIGGER IF EXISTS deskcore_user_calib_updated_at ON autowriter.user_calibration_notes;
CREATE TRIGGER deskcore_user_calib_updated_at
    BEFORE UPDATE ON autowriter.user_calibration_notes
    FOR EACH ROW EXECUTE FUNCTION autowriter._deskcore_touch_updated_at();

ALTER TABLE autowriter.user_calibration_notes ENABLE ROW LEVEL SECURITY;

-- ── 3b. style_edits · 手动精修原始信号 (私有) ────────────────────────
-- 为什么要存原始 diff 而不只存蒸馏后的笔记:
--   generate_calibration_notes(autowriter/memory.py:1154) 的【信号 A · 手动
--   精修差异】是最高权重信号。只留蒸馏结果的话, 换了蒸馏 prompt 或想重算
--   就没有料了 —— 笔记是导出物, diff 才是事实。
-- 只收【人真的动手改了】的对子; 未改就通过的稿子不算教学材料
-- (memory.py:1191-1194 明确拒绝从那里学, 会让模型从偶然选择里编造风格规则)。
CREATE TABLE IF NOT EXISTS autowriter.style_edits (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id  UUID NOT NULL REFERENCES autowriter.projects(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    ai_title    TEXT NOT NULL DEFAULT '',
    ai_body     TEXT NOT NULL DEFAULT '',
    my_title    TEXT NOT NULL DEFAULT '',
    my_body     TEXT NOT NULL DEFAULT '',
    note        TEXT,
    distilled   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE autowriter.style_edits IS
    'deskcore 手动精修 diff(信号 A, 最高权重). 调校笔记的原始料, 可重新蒸馏. D-041.';
COMMENT ON COLUMN autowriter.style_edits.distilled IS
    '是否已被蒸馏进 user_calibration_notes. 重新蒸馏时可整体置回 FALSE.';

CREATE INDEX IF NOT EXISTS style_edits_owner_idx
    ON autowriter.style_edits (project_id, user_id, created_at DESC);

ALTER TABLE autowriter.style_edits ENABLE ROW LEVEL SECURITY;

-- ── 4. items.updated_at ──────────────────────────────────────────────
-- 补 sync_autowriter_decisions_to_prepublish.py:36-40 记录的缺陷.
-- 回填成 created_at 而不是 NOW(), 免得历史行全部看起来"刚改过".
ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

UPDATE autowriter.items
   SET updated_at = created_at
 WHERE updated_at IS NULL;

ALTER TABLE autowriter.items
    ALTER COLUMN updated_at SET DEFAULT NOW();

COMMENT ON COLUMN autowriter.items.updated_at IS
    '人工决策(status/example_label)的最后变更时间. 补 D-041 前"只能按 created_at 过滤导致漏收迟到决策"的缺陷.';

CREATE INDEX IF NOT EXISTS items_updated_at_idx
    ON autowriter.items (updated_at DESC);

DROP TRIGGER IF EXISTS deskcore_items_updated_at ON autowriter.items;
CREATE TRIGGER deskcore_items_updated_at
    BEFORE UPDATE ON autowriter.items
    FOR EACH ROW EXECUTE FUNCTION autowriter._deskcore_touch_updated_at();

COMMIT;

-- ── 校验 (人工跑, 不在事务内) ────────────────────────────────────────
-- SELECT table_name FROM information_schema.tables
--  WHERE table_schema='autowriter'
--    AND table_name IN ('angle_ledger','draft_fingerprints','user_calibration_notes','style_edits');
--   → 应返回 4 行
-- SELECT column_name FROM information_schema.columns
--  WHERE table_schema='autowriter' AND table_name='items' AND column_name='updated_at';
--   → 应返回 1 行
-- SELECT count(*) FROM autowriter.items WHERE updated_at IS NULL;  → 应为 0
