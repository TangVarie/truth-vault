-- v1.16 · 给馆员缓存行记一个「这次选卡跑了多久」(2026-09-21)
--
-- 为什么要有它: 借阅超时这个数今天被猜错了两次 —— 8 秒(原值)不够, 30 秒(第一次修)
-- 也不够。两次都是拍脑袋, 因为【没有任何地方记过冷路径到底多久】:
--   · deskcore 侧算了 elapsed_ms, 但只打进 stdout(Railway 日志), 查不了;
--   · 馆员侧一处耗时都没记。
-- 实测手上只有两个样本(22s 成功 / >30s 超时), 靠两个点定超时值还是在猜。
--
-- 这一列让每一次【真的跑了 LLM 选卡】的调用把耗时留下来, 于是
--   select percentile_cont(0.95) within group (order by select_ms) ...
-- 就能回答"超时该设多少", 而不用再猜第三次。
--
-- ⚠️ 只在【冷路径】写: 命中缓存的那次根本没调 LLM, 记 0 会把分布污染成一堆 0。
--    所以允许 NULL, 且 NULL 的语义是"这行不是这次算出来的"(历史行也如此)。
ALTER TABLE truth_vault.flywheel_librarian_cache
    ADD COLUMN IF NOT EXISTS select_ms INTEGER;

COMMENT ON COLUMN truth_vault.flywheel_librarian_cache.select_ms IS
    '本行的 selected 是哪次 LLM 选卡算出来的、那次跑了多少毫秒。'
    'NULL = 历史行或非本次计算。命中缓存不写这一列(那次没调 LLM)。'
    '用途: 定 deskcore 侧 LIBRARIAN_TIMEOUT_SEC —— 别再拍脑袋 (D-074)。';
