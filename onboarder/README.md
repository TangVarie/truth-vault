# onboarder/ · 接表助手

飞书投放表 → `mappings/<project_id>.yaml` **草稿**。设计/决策见
**[docs/16-onboarding-agent.md](../docs/16-onboarding-agent.md)**。

做「梳理 + 闭集抽取 + 起草」,判断权(方向拆解 / tier 阈值 / 合规)留给策略 lead;
产出永远是带 `[待确认]` 的草稿 + review brief,人审 PR 才进库(README 原则 1)。

## 架构

**确定性取数 + 单次 Anthropic 调用**(librarian 同款,走中转站非流式 —— 已验证能透传)。
`core.draft()` 是核心(不写盘),被两处复用:本地 CLI、Railway 端点。

```
飞书 list_fields(权威列+选项) + N 行样本 + 全表 distinct(枚举型取全集)
  + 历史 mapping/家族指纹/词表(corpus, 跨表对齐)
  → 一次 call_anthropic → ===MAPPING_YAML=== / ===REVIEW_BRIEF===
  → 词表 + D-021 校验 → 草稿
```

## 部署:Railway 跑端点 + GitHub 按钮触发(推荐)

实测 **GitHub Actions 连不上中转站**(海外 runner → 网关超时),但 **Railway 连得上**
(librarian 就在上面)。所以:**Railway 跑 LLM,GitHub 只做 git**。

```
GitHub「Run workflow」填表 ──HTTP──▶ Railway /onboard(连网关+飞书,出草稿)
                                          │ 返回 {mapping_yaml, review_brief, ...}
   GH Action 写文件 + 推 onboarder/draft-<id> 分支 ◀──┘ → 打印开 PR 链接 → 人审
```

**① Railway:新建一个 service**(与 librarian 并存,同一 repo):
- root = repo 根;build `pip install -r onboarder/requirements.txt`;
  start `uvicorn onboarder.app:app --host 0.0.0.0 --port $PORT`;healthcheck `/health`
- env:`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`(**用能跑通的那条通道**)、
  `FEISHU_APP_ID` + `FEISHU_APP_SECRET`、`ONBOARDER_API_KEY`(自己定个口令)、
  可选 `ONBOARDER_MODEL`
- 拿到公网域名,如 `https://onboarder-xxx.up.railway.app`

**② GitHub:加 2 个 repo secret**(Settings → Secrets → Actions):
- `ONBOARDER_URL` = 上面的 Railway 域名
- `ONBOARDER_API_KEY` = 与 Railway 那个 `ONBOARDER_API_KEY` 一致

**③ 跑**:Actions →「接表 agent」→ Run workflow,填 project_id + app_token + table_id
→ 跑完日志里有「👉 点这里开 PR」链接,点开 merge 即审。

## 本地跑(备用,只要 Python)

```bash
pip install -r onboarder/requirements.txt
export ANTHROPIC_BASE_URL=... ANTHROPIC_API_KEY=... FEISHU_APP_ID=... FEISHU_APP_SECRET=...
python -m onboarder.cli --project-id WTG_phase1 \
  --app-token A2sybSE0pa5kcnsukAMcJ9TDngb --table-id tbliiz1N4m9bCRx2 --out-dir out
# 只拼 prompt 不调 LLM/不连飞书:
python -m onboarder.cli --project-id X --dry-run
```
> Windows 看产物别用 `type`(乱码),用 `Get-Content -Encoding UTF8 out\WTG_phase1.yaml`。

## 验收 · WTG 金标准

```bash
python -m onboarder.eval_wtg                              # 校验器/词表/金标准自洽(无需凭证)
python -m onboarder.eval_wtg --against out/WTG_phase1.yaml  # 产出 vs 金标准结构对比
```
WTG 只有**结构部分**定稿,eval 只比结构字段 + `[待确认]` 覆盖,**不**断言草稿判断值。

## 待办

- sync 侧支持「多选 方向 拆成多个基础方向分别套用」(改 `scripts/sync_feishu_notes_to_truth_vault.py`,
  单独、仔细做;只影响真正导入,不影响出草稿)。
