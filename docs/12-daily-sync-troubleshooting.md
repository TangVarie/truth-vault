# docs/12 · Daily TV sync 失败排查手册 (runbook)

> 2026-05-27 一次排查的沉淀。
> 症状: GitHub Actions「Daily TV sync」红叉, 末尾 `Fail job on any sync failure`
> 报 `failed steps: feishu_sync comments_sync ssll_sync aw_sync prepublish_sync`
> (5 个 sync 步骤全挂), 但**每个 sync 步骤在 UI 上显示绿勾 ✓**。

---

## 1. 先看懂: 为什么"绿勾"还会 fail

- `daily-sync.yml` 每个 sync step 都带 `continue-on-error: true` → 步骤内部 Python
  即使报错, UI 也显示绿勾 ✓, 不让 job 立刻变红。
- 真正的失败被记进各 step 的 `outcome`, 最后由 `Fail job on any sync failure`
  这步聚合: 任一 `outcome == failure` → 整 job `exit 1` → GitHub 默认发邮件。
- 所以那条红色 `failed steps: ...` **只是汇总器**, 真正的 Python traceback 藏在
  绿勾步骤内部。
- **看真错的方法**: 点开绿勾步骤 **「TV 爆款 → sanshengliubu.reference_samples
  (通道 1)」** (这步纯 Supabase, `main()` 第一件事就是连库, 报错最干净) → 拉到
  日志最底部, 最后 1–2 行就是根因。

## 2. 根因 (2026-05-27 实锤) · `ClientOptions(schema=None)` 代码 bug

**真正的根因是代码 bug, 与 secret / 项目 / 飞书 / 数据库配置无关。**

`scripts/_common.py: get_supabase_client()` 当时用
`create_client(url, key, ClientOptions(schema=None))`。在锁定的
`supabase==2.30.0` / `postgrest==2.30.0` 下, `schema=None` 被当成
`Accept-Profile` 请求头的值, httpx 构建请求头时对 `None` 调 `.encode()` →
**每次 `.execute()` 都在发出请求之前抛 `AttributeError: 'NoneType' object has no
attribute 'encode'`**。显式 `.schema("truth_vault")` 也盖不住。

为什么这解释了全部现象:
- 5 步都走 `get_supabase_client()` → 第一次 `.execute()` 就崩 → 全挂。
- 崩在发请求之前 → 两个项目 Supabase REST 日志都没有 sync 流量 (不是采样漏, 是真没发)。
- `truth_vault` 14 张表至今 0 行 → 这套 sync **从来没真正跑通过**。
- 换 key / 换 URL 都没用 → 跟 key/url 无关。

本地装 2.30.0 复现验证: `schema=None` → AttributeError; 默认 schema → `.execute()`
正常发出请求。**修复: 已在分支去掉 `ClientOptions(schema=None)`, 改用
`create_client(url, key)` 默认 schema (所有调用点本就显式 `.schema()` 覆盖)。拉最新
分支重跑即可。**

> 教训: 最初凭"日志没流量 + 两库都有 autowriter"推断成"secret 配错项目"是**错的**。
> 没看到真实报错就下结论会翻车。真错一直在绿勾步骤日志底部。

## 3. 重跑后若仍失败 · 才轮到查这些 (真·配置项)

代码 bug 修好前根本走不到下面这些; 修好后若还失败再按此查:

| 查什么 | 正确值 / 做法 |
|---|---|
| `SUPABASE_URL` | `https://kduysqedrclrfevrxiie.supabase.co` (ROC数据飞轮, 有 truth_vault 的库) |
| `SUPABASE_SERVICE_ROLE_KEY` | 同项目 service_role / `sb_secret_` (非 publishable/anon) |
| Exposed schemas | Settings → API 要含 `truth_vault` / `autowriter`, 否则 404 |
| `Host not in allowlist` (403) | 项目 Data API 开了 IP 白名单, GH Actions IP 被挡 → 加 GH IP 段或关限制 |
| 各 mapping `sync_config` | `feishu_app_token` / `feishu_table_id` 配好, 否则仅 feishu_sync 单步失败 |

> 旁注: 账号下另有旧库 `vnbcytilakkxojhgzeqr` (写作工作台停滞备案, D-024 迁移前的
> autowriter 库, 无 truth_vault)。两库都有 autowriter, 别来日把 secret 指错。

## 4. 报错字符串 → 原因 对照表

绿勾步骤底部看到的最后一行, 对照:

| 看到 | 原因 | 怎么修 |
|---|---|---|
| `AttributeError: 'NoneType' object has no attribute 'encode'` | **本次真凶**: `_common` 的 `ClientOptions(schema=None)` (supabase 2.30.0) | 已修 (默认 schema); 拉最新分支重跑 |
| `... starts with 'sb_publishable_'` | 拿成 publishable key | 换 service_role / `sb_secret_` |
| `... has role='anon'` | 拿成 anon key (旧 JWT) | 换 service_role |
| `The schema must be one of the following` (404) | URL 指向没有 truth_vault 的项目, **或** truth_vault 没在 Exposed schemas 里 | URL 改成 `kduysqedrclrfevrxiie`; 并在 Settings → API → Exposed schemas 加 truth_vault/autowriter |
| `Invalid authentication credentials` (401) | key 是别的项目的 / 已失效 | key 换成本项目 service_role |
| `Host not in allowlist` (403) | 项目 Data API 开了 IP 白名单, 当前 IP 被挡 | 加 GitHub Actions IP 段, 或关掉网络限制 |
| `... env vars must be set` | secret 为空 | 填上 |

## 5. 验证修好了

1. Actions → Daily TV sync → Run workflow (先 `dry_run = false`), 看是否全绿。
2. 确认数据真写进去了 (任一):
   - flywheel 状态步骤日志里各项目 `baokuan` 数 > 0;
   - 或 SQL: `select count(*) from truth_vault.notes;` (修好前是 0)。

## 6. 推荐改进 (下个窗口做, 需用真 secret 测过再合)

现状: 失败要点开绿勾步骤翻日志才看得到根因, 对新手不友好。建议在 `daily-sync.yml`
的「Check secrets」之后、所有 sync step 之前加一个**硬性 preflight gate**
(**不要**加 `continue-on-error`), 连库失败就立刻红 + 打印 checklist:

```yaml
- name: Preflight · 验证 Supabase 连接 (fail fast)
  if: steps.check.outputs.skip != 'true'
  id: preflight
  working-directory: scripts
  run: |
    python - <<'PY'
    import sys
    from _common import get_supabase_client, mask_secrets
    try:
        sb = get_supabase_client()
        sb.schema("truth_vault").table("projects").select("project_id").limit(1).execute()
    except Exception as e:
        print("::error::Supabase preflight 失败 — 先修这个再跑 sync。")
        print(f"::error::{type(e).__name__}: {mask_secrets(str(e))}")
        print("查: SUPABASE_URL 指向有 truth_vault 的项目? "
              "key 是同项目 service_role (非 publishable/anon)? 无首尾空格?")
        sys.exit(1)
    print("✅ preflight OK — truth_vault 可达。")
    PY
```

注意事项 (务必):

- 这是 gate, 配错会立刻挡住整个 job —— **先用一次故意填错的 key 跑一遍, 确认它
  如预期变红; 再用正确 key 确认它放行; 然后才合并。** 不要未测就合。
- 把 `preflight` 也加进末尾 `Fail job on any sync failure` 聚合 step 的判断里
  (`if [ "${{ steps.preflight.outcome }}" = "failure" ]`...), 保持失败消息一致。

---

## 7. 飞轮健康自查 (R-022 / 通道1 下游验证)

> 跟上面的"sync 失败排查"用途不同: 这节是 **sync 都绿了之后, 验证飞轮在 ssll 侧
> 真闭环** —— ① TV 把爆款上架到 `public.reference_samples`(写入), ② ssll 写稿时
> 真检索并用了它们(消费)。R-022 修的就是后半段(ssll 之前用硬编码假样本, 见 docs/10 R-022)。

一键跑(只读, 不写库):

```bash
cd scripts
python check_flywheel_health.py                # 人读报告
python check_flywheel_health.py --json          # 机器可读(给 cron / 监控)
python check_flywheel_health.py --days 14        # 放宽 Check 2 审计窗口
```

脚本跑四个检查:

| 检查 | 看什么 | ✅ 通过 | ⚠️ / ℹ️ |
|---|---|---|---|
| 1 · TV→ssll 上架 | `reference_samples` 里 TV 来源样本数 | tv_origin > 0 且随飞书标 tier 增长 | =0 → 提示:还没爆/大爆/参考同步到 ssll(**不算失败**) |
| 2 · ssll 真用了吗 | `stage_logs.r022_flywheel_audit` 的 `db_hit_rate` | 有行且 hit_rate ≥ 0.3 | 0 行 → 提示:ssll 还没跑过 vibe_loop,去触发一次再来;hit_rate < 0.3 → 告警 |
| 3 · 飞轮告警 | 近 24h `status='completed_warn'` | 0 条 | >0 → 告警(查 missing_tag / excess_static_use) |
| 4 · 样本检索得到吗 | TV 来源样本的 platform/category | 都非空 | 有空 → 告警(ssll 退化成 platform-only 检索, 见 docs/13) |

退出码: `0` = 健康 / 仅提示; `1` = 有可处理问题。**"0 审计行" 是提示不是失败** —— 它只
说明 ssll 还没产出过内容、无从验证它真用了样本;触发一次 ssll vibe_loop 后再跑本脚本。

**关键认知**: Check 1(上架)和 Check 2(消费)是两件事。R-022 的代码已复核正确
(ssll PR #27+#28, docs/10), 但 **"它真用了" 要靠 Check 2 的审计行证明**, 而审计行只在
ssll 真写过稿后才有。所以新部署的正常节奏: 标爆款 → Check 1 看上架 → 触发 ssll 写一次
→ Check 2/3 看命中率和告警 → Check 4 排查"为什么没命中"。

原始 SQL(不想跑脚本时手查)+ 字段定义(`db_sourced` / `static_sourced` / `total_vibe_cells`)
见 [docs/10 "TV 日报跨仓查 R-022 audit"](10-sister-repo-followups.md)。建议把本脚本接进
`daily-sync.yml`(sync 步骤之后), 让飞轮健康每天自动可见。

> **2026-06-01 现场快照**: Check 1 = 1(参考笔记 `WTG_phase1_recvk9VPCTNG1b` 已上架,
> 写入路径实锤); Check 2 = 0 审计行(ssll 还没跑过 vibe_loop, 消费侧待验)。即"货上架了、
> 还没人来借过"。

---

## 8. 备用中转站 (D-148)

> 2026-11-10 加。起因: 11-09 起主中转站慢了约 5 倍、时不时不回话 (1 个 token 的 ping 25 秒没回; 两篇特征层超过
> Railway 边缘 300 秒 → 502, 之后 worker 锁 409; 夜跑 essence 一篇 81 秒, 平时 13–16 秒)。配一个备用站, 主站出事时
> 自动临时改走备用站, 不至于一直卡着。代码在仓库根 `relay_failover.py` (autowriter `relay_failover.py`、
> Jev `judge/relay.py` 是同一份); CI 守卫 `scripts/check_relay_failover.py` (由 `check_prompt_cache_fallback.py` 带着跑)。

**启用**：在每个调 Claude 的地方加两个变量（三个仓同名）：`ANTHROPIC_BASE_URL_BACKUP`（备用站地址）和 `ANTHROPIC_API_KEY_BACKUP`（备用站 key）。两个都填了才算启用，缺一个等于没配，行为和现在完全一样。GitHub（truth-vault）：Settings → Secrets and variables → Actions → **Secrets** 新建这两个（地址也放 secret，别放 variable，variable 会原样出现在公开日志里）。Railway：truth-vault 的 tv-worker / librarian / onboarder、Jev 的 judge，各自 Variables 里加这两个（改变量会自动重新部署）。autowriter 的 Streamlit / worker 以后开起来时同样加。加完跑一次 Actions → gateway-probe，`target` 选 `backup`（或 `both`），看备用站 `http=200`。备用站必须认同样的模型名（claude-sonnet-5-5 / claude-haiku-5-5），不认会回 404/503。备用站的 Haiku 如果是单独的通道 key（11-10 起就是这样），在 GitHub Secrets 再加 `ANTHROPIC_API_KEY_BACKUP_HAIKU`：只有模型名带 haiku 的调用（夜跑的外部帖遮挡词）用它，地址还是 `ANTHROPIC_BASE_URL_BACKUP`；Railway 上不用加（那边不调 Haiku）。gateway-probe 测备用站的 haiku 时也用这把。

**自动切换**：配好后每次调用先打主站，但主站只给一次机会且限时（夜跑标注 60 秒、遮挡词 150 秒、馆员 22 秒、上表流式 90 秒没有新字节、Jev 规则编译沿用 JUDGE_COMPILE_TIMEOUT_SEC）。主站超时、连不上、429、5xx（含 520/522/524/529）、401/402/403（多半是余额或 key 失效）、404（多半是不认模型名）→ 这次立刻改打备用站。400 这类请求本身有问题的不切；中转站敏感词拦截（sensitive_words_detected）也不切，照旧按 D-125 记 NULL。主站连续 2 次失败，或连续 2 次慢得离谱（单次超过 25 秒；遮挡词 60 秒、馆员 25 秒）→ 熔断 20 分钟：这期间所有调用直接走备用站；到点放一个调用去试主站，好了切回，不行再熔断 20 分钟。同一台机器上的进程共用熔断状态（夜跑一个项目熔断了，下一个项目直接走备用）。

**手动切换**：变量 `RELAY_FORCE`：`backup` = 只走备用站；`primary` = 只走主站、不切换，和没配备用站时一模一样；留空或删掉 = 自动。GitHub 在 Settings → Secrets and variables → Actions → **Variables** 设；Railway 在对应服务的 Variables 设（会重新部署）。备用站没配时设 `backup` 不生效，日志会提示一行。

**怎么看走的是哪条**：夜跑日志里 essence / 特征层 / 策展的 `Done:` 行多一个 `"relay": {...}`（只在配了备用站时出现）：`mode`、`primary_ok` / `primary_slow` / `primary_fail`、`backup_ok` / `backup_fail`、`breaker_open_skips`（熔断期间直接走备用的次数）、`breaker`（closed 正常 / open 熔断中 / half_open 该试主站了）。第一次切换打一行 `relay: primary failed (HTTP 503); failing over to backup`，熔断打 `relay: breaker open for 1200s ...`，进程结束打 `relay summary: {...}`。Railway 各服务和 Jev 的 `/health` 有 `relay` 字段：`relay_mode`（primary_only / auto / backup_only）、`relay_backup_configured`、`relay_force`、`relay_breaker`（off / closed / open / half_open），馆员 / 上表 / Jev 还带本进程计数 `relay_counts`。日志和 /health 只出现 primary / backup、状态码、错误类型、耗时和次数，从不出现地址、key 或中转站返回的报错原文。

> 在哪看得到这几行：daily-sync 的 essence 那步（两趟）11-11 起把 `relay: ` 开头的单行也过滤进 Actions 日志（切换那一行、熔断开 / 合那两行；`relay summary:` 不带 `relay: `，进不来，计数看 `Done:` 行）。11-11 那晚第一次看到：essence 那步里 2 行 `relay: `；主站那次是超时，超时没有 HTTP 状态码，行里只有错误类型。daily-sync 的策展步骤和 backfill-essence / recurate-lessons 照旧只把 `Done:` 等几行打进日志，那三种 `relay:` 单行平时看不到，只有脚本退非零时才跟着最后十来行一起出来。所以平时**看 `Done:` 行里的 `relay` 就够**：`primary_fail` / `primary_slow` 大于 0 = 主站出过事，`breaker` 是 `open` = 这会儿在走备用站。特征层（features-sync → Railway worker）同理，看它打出来的 `Done:` 行。Railway 的 librarian / onboarder 在服务自己的日志里能看到这几行单行。

**备用站自己坏了怎么办**：熔断期间所有调用只打备用站，备用站报错就算这次失败，不会回头再打主站（主站只是慢、其实还能用的时候也一样）。所以 `Done:` 行里 `backup_fail` 多、`breaker` 是 `open` 时，先跑 gateway-probe（`target` 选 `backup`）看备用站；一时修不好就把 `RELAY_FORCE` 设成 `primary`（回到没配备用站的老样子，GitHub variable 和 Railway 各服务都要设），修好再清空。备用站平时几乎用不上，余额用完或 key 过期很难自己发现，建议隔一阵用 gateway-probe 的 `backup` 测一次。

**代价**：备用站另外计费；主站超时那次主站可能已经扣了钱；两个站的 prompt cache 不通用，切过去后头几次没有缓存命中。可调（一般不用动）：`RELAY_PRIMARY_TIMEOUT_S`、`RELAY_SLOW_S`（0 = 不按慢判）、`RELAY_BREAKER_FAILS`、`RELAY_BREAKER_COOLDOWN_S`。

本仓接在哪 (truth-vault):

| 调用点 | 主站限时 / 慢门槛 | 备用站客户端 |
|---|---|---|
| `scripts/annotate_essence_pass.call_claude` (essence、子方向、canary、策展、特征层 `_llm`、评论归线、外部候选; 遮挡词 `mask_external_names` 走 max_tokens 8000 那档) | 60 秒 / 25 秒 (max_tokens > 4000: 150 / 60) | SDK 默认重试与超时 (同老主站) |
| `librarian/clients.call_anthropic` | 22 秒 (`RELAY_PRIMARY_TIMEOUT_S` 超过 40 按 40; 整轮 60 秒, 见 `librarian/README.md`「时限」) / 25 秒 | `max_retries=0`, 单次 45 秒 |
| `onboarder/clients.call_anthropic` | 流式 90 秒没有新字节 / 不按慢判; 非流式 600 秒 | `max_retries=0` (同老主站, 重试只留外面一层) |
| `worker/app.py` | 自己不调; 子进程继承 env; `/health` 只回显模式与熔断 | — |

GitHub: daily-sync / backfill-essence / recurate-lessons / feature-discovery 的 job env 带这两个 secret 和 `RELAY_FORCE`;
features-sync / backfill-features / onboard-table 的模型调用在 Railway, 变量配在 Railway。

已知没改的 (另开一单): 几条老日志会把**一个**异常的原文打出来 (特征层 `systemic` 行、essence `api_error: {exc!r}`、
策展 `%r`、遮挡词 `str(exc)[:160]`、馆员缓存降级 warning), 配了备用站后那个异常可能是备用站的。改它们会让没配备用站时的
日志也变、还要动 ci.yml 的钉子, 不在这次。
