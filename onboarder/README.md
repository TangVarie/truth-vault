# onboarder/ · 接表助手

飞书投放表 → `mappings/<project_id>.yaml` **草稿**。设计/决策见
**[docs/16-onboarding-agent.md](../docs/16-onboarding-agent.md)**。

做「梳理 + 闭集抽取 + 起草」,判断权(方向拆解 / tier 阈值 / 合规)留给策略 lead;
产出永远是带 `[待确认]` 的草稿 + review brief,人审 PR 才进库(README 原则 1)。

## 架构(为什么不是 agent)

**确定性取数 + 单次 Anthropic 调用**(librarian 同款,走中转站非流式 —— 已验证能透传)。
不用 agent-sdk / claude CLI / Node。原先用 Agent SDK 的 agent 循环 + 进程内 MCP 工具,
实测那条路太脆(网关流式连不上、工具不暴露),而本任务本就是"取数 → 一次推理",
单次调用更稳更省。

## 流程(`core.run_onboarding`)

1. **飞书**:`list_fields`(权威列名 + 单选/多选**完整选项**)+ N 行文案样本 +
   **全表 distinct**(枚举型列取**全集**,不靠样本 → 稀有方向不漏)
2. **corpus**:历史 `mappings/*.yaml` + 家族指纹 + 词表(跨表对齐)
3. **一次** `call_anthropic` → `{mapping_yaml, review_brief}`
4. **校验**(词表闭集 + D-021 列覆盖)→ 写 `out/<id>.yaml` + `out/<id>.brief.md`

## 额度 / 网络

走中转站(`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`,同 librarian)。

> ⚠️ 必须从**能连到中转站的网络**跑。实测 **GitHub Actions 连不上你的网关**(curl 超时),
> 所以**本地 / Railway** 跑;GH Actions 那条要等网关放行 GH 的 IP,或改用官方 endpoint。

## 本地跑(Win / Mac / Linux 通用 —— 只要 Python,不要 Node)

```bash
pip install -r onboarder/requirements.txt
# 设 4 个环境变量(你已知好用的值;Win 用 $env:VAR="...",Mac/Linux 用 export VAR=...):
#   ANTHROPIC_BASE_URL   ANTHROPIC_API_KEY   FEISHU_APP_ID   FEISHU_APP_SECRET
python -m onboarder.cli --project-id WTG_phase1 \
  --app-token A2sybSE0pa5kcnsukAMcJ9TDngb --table-id tbliiz1N4m9bCRx2 --out-dir out
```

只拼 prompt 看看(不连飞书、不调 LLM):
`python -m onboarder.cli --project-id X --dry-run`

## 验收 · WTG 金标准

```bash
python -m onboarder.eval_wtg                              # 校验器/词表/金标准自洽(无需凭证)
python -m onboarder.eval_wtg --against out/WTG_phase1.yaml  # 产出 vs 金标准结构对比
```

WTG 只有**结构部分**定稿,eval 只比结构字段 + `[待确认]` 覆盖,**不**断言草稿的判断值。
