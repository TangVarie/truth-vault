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

## 2. 根因 (本次诊断结论)

5 个步骤里 comments / ssll / aw / prepublish **完全不碰飞书、纯 Supabase**, 也全挂
→ 共因是 **Supabase 连接**, 不是飞书、不是某一个脚本的逻辑。

用 Supabase MCP 核实到的关键事实:

- 账号下有**两个项目, 而且都有 `autowriter` schema** (← 最容易混淆的根源):

  | 项目 ref | 名称 | 有 `truth_vault`? |
  |---|---|---|
  | `kduysqedrclrfevrxiie` | ROC数据飞轮-workstation | ✅ **有** (本仓库目标库) |
  | `vnbcytilakkxojhgzeqr` | 写作工作台停滞备案数据库 | ❌ 只有 autowriter |

- sync 用**单一** `SUPABASE_URL` + **单一** `SUPABASE_SERVICE_ROLE_KEY`, 通过
  `.schema("truth_vault" / "public" / "autowriter")` 跨 schema 访问 —— 这些 schema
  都在**同一个项目**内 (见 `scripts/_common.py: get_supabase_client`)。
  ssll 的 `reference_samples` 在 **`public` schema** (D-024), 不是独立 schema,
  也是同一个项目, 不存在跨项目。
- 诊断时两个项目的 REST `api` 日志都**没有这次 sync 的请求** (只有健康检查 + 一条
  约 23h 前的旧 auth 400) → sync 在**连库之前**就挂了 (命中 `_common.py` 的 key
  格式校验抛 `RuntimeError`, 根本没发出网络请求, 所以日志为空)。
- 数据库本身健康: `truth_vault` 14 张表都在, 只是**全部 0 行** = 从未成功写入过。

**结论: 纯 GitHub Secret 配置问题 —— 不是代码 bug, 不是飞书, 不是数据库。**

## 3. 修复 (照做)

GitHub → 仓库 **Settings → Secrets and variables → Actions**, 确认下面两个值
**同时指向 `kduysqedrclrfevrxiie`**:

| Secret | 必须的值 | 来源 |
|---|---|---|
| `SUPABASE_URL` | `https://kduysqedrclrfevrxiie.supabase.co` | 项目「ROC数据飞轮-workstation」→ Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 同项目的 service_role / `sb_secret_...` | 同项目 → Settings → API → service_role secret |

四个最常踩的坑 (任一都会让 5 步全挂):

1. URL 或 key 填成了另一个项目 `vnbcytilakkxojhgzeqr` → 它没有 truth_vault → 404
2. key 拿成了 **publishable / anon** (新面板 publishable 最显眼, secret 要单独点开)
   → `_common` 会直接拒绝
3. URL 和 key **不是同一个**项目的
4. 复制时带了首尾空格 / 换行

## 4. 报错字符串 → 原因 对照表

绿勾步骤底部看到的最后一行, 对照:

| 看到 | 原因 | 怎么修 |
|---|---|---|
| `... starts with 'sb_publishable_'` | 拿成 publishable key | 换 service_role / `sb_secret_` |
| `... has role='anon'` | 拿成 anon key (旧 JWT) | 换 service_role |
| `The schema must be one of the following` (404) | URL 指向没有 truth_vault 的项目 | URL 改成 `kduysqedrclrfevrxiie` |
| `Invalid authentication credentials` (401) | key 是别的项目的 / 已失效 | key 换成本项目 service_role |
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
