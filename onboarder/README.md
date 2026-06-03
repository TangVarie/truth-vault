# onboarder/ · 接表 agent

飞书投放表 → `mappings/<project_id>.yaml` **草稿** 的自动起草 agent。
设计/决策见 **[docs/16-onboarding-agent.md](../docs/16-onboarding-agent.md)**。

agent 干「梳理 + 闭集抽取 + 起草」,判断权(方向拆解 / tier 阈值 / 合规)留给策略
lead(README 原则 1)。产出永远是带 `[待确认]` 的草稿 + review brief,人审 PR 才进库。

## 流程

```
read_mapping_corpus   读词表+家族指纹+历史 mapping(跨表对齐、复用已有拆解)
   → pull_feishu_table   拉列 + 样本行
   → 起草整份 yaml(锁受控词表;判断项标 [待确认])
   → recommend_thresholds 按互动量分布推荐阈值
   → validate_mapping_yaml 自查(errors=0 且 D-021 列全覆盖)
   → emit_draft          写 draft yaml + brief(再校验一次兜底)
```

护栏:`PreToolUse` hook 只放行 onboarder 工具(挡内建 Bash/Write);`emit_draft`
词表 error / 未覆盖列 → 拒绝写盘;`max_budget_usd` + `max_turns` 封顶成本;
`setting_sources=[]` 不读本机配置。

## 额度

走**中转站**(同 `librarian` 池子):CLI 读 `ANTHROPIC_BASE_URL` +
`ANTHROPIC_API_KEY`(中转站若要 bearer 则用 `ANTHROPIC_AUTH_TOKEN`)。
**不**用 Claude 订阅额度(每周封顶 + 交互专用,见 docs/16)。

## 本地跑

```bash
# 1) 装依赖 + Claude Code CLI(agent SDK 底层驱动它)
pip install -r onboarder/requirements.txt
npm install -g @anthropic-ai/claude-code

# 2) 只看 prompt/工具(不调 LLM、不连飞书):
python -m onboarder.cli --project-id TXQ_phase1 --app-token x --table-id y --dry-run

# 3) 真跑(需下面的环境变量):
export ANTHROPIC_BASE_URL=...   ANTHROPIC_API_KEY=...      # 中转站
export FEISHU_APP_ID=...        FEISHU_APP_SECRET=...      # 飞书 bot
python -m onboarder.cli --project-id TXQ_phase1 --app-token bascnXXX --table-id tblXXX
```

## CI / 运营

GitHub Actions `workflow_dispatch`([.github/workflows/onboard-table.yml](../.github/workflows/onboard-table.yml)):
填 `project_id` + 飞书 `app_token`/`table_id` → agent 起草 → **自动开 PR**(yaml + brief)
→ 策略 lead 审 / 改 / merge。成本在中转站用量面板看。

## 验收 · WTG 金标准

```bash
# 校验器 + 词表 + 金标准 三者自洽(现在就能跑,无需任何凭证):
python -m onboarder.eval_wtg
# agent 重跑 WTG 后,产出 vs 金标准结构对比:
python -m onboarder.eval_wtg --against /tmp/WTG_phase1.yaml
```

通过判据:结构 diff=0(schema_family / field_mapping 列集 / raw_extra / tier 规则 /
阈值 / 方向名),且 `[待确认]` 项 ⊇ 金标准。
