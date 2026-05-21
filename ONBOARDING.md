# Truth Vault · 新人 ONBOARDING

> 给第一次接手这个项目的工程师 / 分析师 / Claude session。**先看这个**，再看其它文档。

---

## 30 秒判断：现在到底处于什么状态

```
┌─────────────────────────────────────────────────────────────────────┐
│  代码状态:    ✅ Sprint 0 就绪 (40 文件 · 6 个 sync 脚本 · 全部本地烟测过)│
│  部署状态:    ⬜ 0% — 还没有任何 sync 在真实数据上跑过                │
│  阻塞点:      Sprint 0 dry-run 验收 (需要共享 Supabase + 凭证)        │
│  Sprint 1 缺口: 见 CURRENT_STATE.md "已知 gap" (4 项 P1)              │
│  下一步:      见下方 "新人第一周 checklist"                           │
└─────────────────────────────────────────────────────────────────────┘
```

**翻译**：飞轮还没转起来。Sprint 0 范围内代码可以跑、SQL 可以应用；但
Sprint 1 仍有 4 个 LLM/sync 待补（comments 楼层重建、sub_directions
LLM 分类、essence 标注、prepublish_evaluations 反推），详见
`CURRENT_STATE.md`。先把基础设施搭起来才能跑第一次真实数据。

---

## 新人第一周 checklist

按以下顺序，每一步打钩了再下一步。卡在任何一步先看「找谁要凭证 / 谁拍板」节。

### Day 1 · 理解项目（不动代码）

- [ ] 读 `README.md` (30 分钟) — 完整目录结构 + 项目宪法
- [ ] 读 `CURRENT_STATE.md` (10 分钟) — Sprint 0 scope + 已知 gap
- [ ] 读 `docs/09-system-integration.md` (15 分钟) — 双通道集成核心
- [ ] 读 `docs/01-architecture.md` (15 分钟) — 三层架构论证
- [ ] **读 `RISKS.md`** (10 分钟) — 部署前 blocker (R-001~R-004 必须在你拿凭证前知道)
- [ ] 跳读 `DECISIONS.md` (重点看 D-024 / D-028 / D-034 / D-035)
- [ ] **反向陈述当前理解给 Ziao 确认**

### Day 2 · 本地 sandbox

- [ ] clone 仓库到本地
- [ ] `cd scripts && python3 -m venv venv && source venv/bin/activate`
- [ ] `pip install -r requirements.txt`
- [ ] `cp .env.example .env` (先不填，只是检查模板格式)
- [ ] 本地起 Postgres 16, 跑 `schemas/notes_v1_2.sql` 看是否全绿
- [ ] 跑 comment parser 单测验证环境:
  ```bash
  python -c "from sync_comments_from_raw_extra import parse_comment_text; \
             print(list(parse_comment_text('1. 用户A: hello\n贴主: thanks')))"
  # 期望: [('素人', 'hello'), ('贴主', 'thanks')]
  ```

### Day 3-4 · 拿凭证 + 接入共享 Supabase

- [ ] 找 Ziao 要：
  - [ ] 共享 Supabase project 的 URL + service_role key
  - [ ] 飞书 app_id / app_secret (用于读多维表)
  - [ ] Anthropic API key (用于 essence 标注 LLM pass)
  - [ ] autowriter 当前部署位置 (确认场景 A vs B,见 RUNBOOK)
- [ ] 填到 `.env` (生产环境用 GitHub Secrets / 系统 env，绝不 commit)
- [ ] 在 Supabase Dashboard → Settings → API → Exposed schemas 加
      `autowriter` + `truth_vault` (默认只有 public)

### Day 4-5 · 部署 schema (在 staging 上)

- [ ] 跑 `schemas/notes_v1_2.sql` → 创建 truth_vault schema
- [ ] 按 `autowriter-migrations/RUNBOOK.md` 跑场景 A 或 B
- [ ] 跑 `sanshengliubu-patches/001_add_source_tv_note_id.sql`
- [ ] **autowriter 数据迁移要协调停机窗口** — 找 autowriter 维护者
- [ ] 三个 schema 全部就绪后跑 `schemas/notes_v1_2_cross_schema_views.sql`

### Day 5 · 第一次 dry-run

- [ ] 在 mapping yaml 里填 `sync_config.feishu_app_token` + `feishu_table_id` (NUC_phase1)
- [ ] 跑 `sync_feishu_notes_to_truth_vault.py NUC_phase1 --dry-run --limit 5`
- [ ] 看 stdout 日志，确认字段映射正确
- [ ] 跑 `sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run`
- [ ] 跑 `sync_truth_vault_baokuan_to_autowriter_items.py --dry-run`

### Week 2 起：真实数据

- 跑 NUC_phase1 全量 1102 行 → 在 staging Supabase 看数据
- 抽 30 条人工核对 tier 抽取 / direction_decomposition 正确性
- 触发双通道 sync，看 ssll vibe_rewriter / autowriter system prompt 是否真的拿到了 TV 爆款
- 跑 essence annotation pilot 30 条 (Anthropic API)

详细见 `CURRENT_STATE.md` 的"下一步要做的事"节。

---

## 找谁要凭证 / 谁拍板

| 需要的东西 | 找谁 | 备注 |
|---|---|---|
| 共享 Supabase 凭证 | Ziao | service_role key 不要进任何前端 |
| 飞书 app_id/app_secret | Ziao | 飞书开放平台 → 应用凭证 |
| Anthropic API key | Ziao | 按预算控制 `--limit` |
| autowriter 维护权限 | 待补 (问 Ziao) | 场景 A 需要停机迁移 |
| 蓝词 / category 词表新增 | Ziao + 周哥 | 见 docs/05-controlled-vocab.md |
| NRT_2/3 category 决议 (处方药 vs OTC) | Ziao + 周哥 | NUC pilot 之后讨论 |
| Sprint scope 调整 | Ziao | 任何动 D-001~D-035 决策的事 |
| 词表 v0.3 升级 | Ziao + 周哥 | 见 DECISIONS.md 词表演化规则 |

**升级路径**：脚本 bug / 文档错别字 → 直接 PR；架构调整 / 决策推翻 →
先在 DECISIONS.md 加一条新决策再改代码。

---

## 第一周常见问题 (FAQ)

### Q: 为什么飞轮还没转起来？代码不是都写好了吗？

代码 100% ready，但依赖外部资源：
- 共享 Supabase 实例没建
- autowriter 还在独立 Supabase 上（场景 A 需要迁移）
- 飞书 API 凭证没批
- 没有人在真实数据上跑过 dry-run

工程上无 blocker，业务上需要 Ziao 拍板 + 工程师拿凭证。

### Q: 我能改 schema 吗？

可以。流程：
1. 在 `DECISIONS.md` 加一条新决策（说清楚 What / Why / Rejected / Implications）
2. 改 `schemas/notes_v1_2.sql` (或写一个新 migration)
3. 同步改 `docs/02-schema-v1.md` 描述
4. 同步改 `scripts/_common.py` 或具体 sync 脚本如果列名变了
5. 跑本地烟测验证应用通过

**最容易踩的坑**：改了 `truth_vault.notes` 字段名忘了同步
`sync_truth_vault_baokuan_to_sanshengliubu.py:build_reference_sample` 里
的列映射。两侧不一致时 `preflight_check()` 会直接拦截，但只对 ssll 侧
有 preflight，autowriter 侧没有。

### Q: 我能改词表 (controlled-vocab) 吗？

按 D-001 决策，词表演化有严格规则：
- 添加新值容易（写 DECISIONS + 升级 vocab_version）
- 删除现有值困难（需要先迁移所有使用此值的历史数据）
- 拆分值需要重标所有受影响数据（用 Opus 重跑）

词表 v0.2 → v0.3 升级见 `docs/06-essence-annotation.md` 末尾。

### Q: Mode A label leakage 校验把我的 prompt 拦下来了！

参考 `prompts/essence_annotator.md` 「⚠️ 双模式标注」节。Session #9 之后的
校验是**白盒**的，只看 template + project_context 里有没有 performance
占位符 / 关键词。title/body 里出现"大爆款" / "互动"是允许的（那是内容
本身的话题）。如果还被拦：

1. 检查 `build_project_context()` 是否泄露了 tier / interactions
2. 检查 `MODE_A_PROMPT_TEMPLATE` 里有没有混入 `{tier}` `{performance}` 这种占位符
3. 不要试图禁用校验

### Q: sync 报 `column X does not exist` 怎么办？

- ssll 通道：脚本启动时 `preflight_check()` 会做一次列存在性扫描，如果
  报这个，按错误提示对账 sanshengliubu 的实际 schema → 修改
  `build_reference_sample` 列名 + 同步 `docs/09` 数据映射表 + `preflight_check` 必填列列表 + 文档注释 四处一起改
- autowriter 通道：通常是 `external_source` 没加，跑 `autowriter-migrations/002_add_external_source.sql`

### Q: 我跑 sync 卡死在 Supabase 1000 行的回包上限了？

不应该。Session #9 已经把所有 fetch 路径都加了 `fetch_all_pages()` 分页。
如果你看到结果像被截断的，可能是：

- 你写了新 fetch 函数没用 helper → 加 `fetch_all_pages(q)`
- Supabase Dashboard 调过 Max Rows → 适配新上限
- 中间有别的瓶颈 (RLS / 网络) → 加日志看实际返回行数

---

## 跨仓库联动

Truth Vault 不是孤岛，跨三个仓库：

```
┌───────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ truth-vault (本)  │ ───[1]──► sanshengliubu   │         │ autowriter       │
│                   │ ───[2]──►─────────────────► ◄───[3]──┤                  │
│ scripts/ 跨 schema │         │ public schema    │         │ autowriter schema│
│ INSERT 到 [1][2]   │         │ + reference_     │         │ + items.external_│
│ 反向读 [3] 找负例  │         │   samples 加列   │         │   source 加列     │
└───────────────────┘         └──────────────────┘         └──────────────────┘
        │                              │                              │
        │ 集成包路径                   │                              │
        ▼                              ▼                              ▼
sanshengliubu-patches/         (跑 001_add_source_tv_         autowriter-migrations/
                                note_id.sql)                  (跑 001/002/003 + RUNBOOK)
```

新人接手时：
1. 找 sanshengliubu 维护者 → 跑通道 1 patch (1 个 SQL 文件,30 秒)
2. 找 autowriter 维护者 → 按 RUNBOOK 跑通道 2 (有数据迁移,需要停机窗口)
3. 自己负责 truth-vault 仓库 + 共享 Supabase 的 truth_vault schema

---

## 接下来读什么

完成 Day 1 checklist 后，按角色读：

- **工程实施** → `scripts/README.md` + `sanshengliubu-patches/README.md` + `autowriter-migrations/RUNBOOK.md`
- **数据 / 标注** → `docs/03-mapping-protocol.md` + `docs/05-controlled-vocab.md` + `prompts/essence_annotator.md`
- **业务 / 策略** → `docs/04-onboarding-sop.md` + `data-analysis/10-project-audit.md`

更多在 `README.md` 的"文档导航（按角色）"节。
