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
