-- truth_vault v1.5 · 馆员结果缓存 (pull / 图书馆 + LLM 馆员 的"省钱层")
-- ════════════════════════════════════════════════════════════════════
-- 背景 (D-038 / docs/14 §4.2): LLM 馆员按 brief 挑选经验卡的结果, 只要
--   (brief 没变) 且 (库没新增/重策展) 就是稳定的。做一张【内容寻址缓存】:
--   命中直接返回上次精选、跳过 LLM; 未命中才真跑馆员。爆款稀少(库几乎不变)
--   + brief 稳定(项目 system_prompt 包为主体) → 命中率极高, 绝大多数请求 0 LLM。
--
-- 自动失效: cache_key 里含 library_version(= 经验卡 max(updated_at), 见 v1.4 的
--   updated_at + 触发器)。新爆款入库 / 重策展 → library_version 变 → 旧 key 不再
--   命中 → 自然重算; brief 改 → brief_digest 变 → 重算。无需手动清缓存。
--
-- 谁读写: 馆员服务(FastAPI on Railway, R-032/R-033 的依赖) 用 service_role 读写。
--   纯后台数据, 不开放给 anon/登录用户(RLS enable, service_role 绕过)。
--
-- 本迁移在 notes_v1_4_flywheel_lesson_cards.sql 之后应用。
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.flywheel_librarian_cache (
    -- 内容寻址主键: hash(consumer + project_id + brief_digest + library_version)。
    -- 由馆员服务算出后做 PK, 命中=同 brief 同库版本, 直接复用 selected。
    cache_key       TEXT PRIMARY KEY,

    consumer        TEXT,        -- 'autowriter' / 'sanshengliubu' (debug/观测用)
    project_id      TEXT,        -- 消费方项目标识 (aw/ssll 的, 非 truth_vault FK; debug 用)
    brief_digest    TEXT,        -- 本次 brief 的摘要 hash (变了就 miss)
    library_version TEXT,        -- 计算时的库版本 (经验卡 max(updated_at)/计数器; 变了就 miss)

    selected        JSONB,       -- 馆员精选结果: [{source_note_id, why_relevant, borrow_what, excerpt}, ...]

    created_at      TIMESTAMP DEFAULT NOW(),
    last_hit_at     TIMESTAMP    -- 最近一次命中 (LRU 式清理 + 观测; 馆员命中时更新)
);

-- TTL / LRU 清理用 (失效的旧 key 因 key 含 library_version 自然 miss, 不会被命中,
-- 但行会累积; 按 created_at / last_hit_at 定期 prune)。
CREATE INDEX IF NOT EXISTS idx_tv_librarian_cache_created
    ON truth_vault.flywheel_librarian_cache(created_at);
CREATE INDEX IF NOT EXISTS idx_tv_librarian_cache_version
    ON truth_vault.flywheel_librarian_cache(library_version);

-- RLS: 后台缓存, 只由馆员服务 service_role 读写; 不开放 anon/登录用户。
ALTER TABLE truth_vault.flywheel_librarian_cache ENABLE ROW LEVEL SECURITY;
