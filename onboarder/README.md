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

批量(N 张)在**调用方**编排:`batch.py` 逐表打上面这条链路,一张挂了不拖垮整批,
最后汇总成一个分支/PR。见下方「批量」节 + DECISIONS D-044。

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
  `FEISHU_APP_ID` + `FEISHU_APP_SECRET`、**`ONBOARDER_API_KEY`**(自己定个口令,
  **必填** —— 见下)、可选 `ONBOARDER_MODEL`

  > ⚠️ **`ONBOARDER_API_KEY` 不设 = 所有业务请求 401**(2026-08-26,跨库审计
  > SUP-001)。服务照常起、`/health` 照常 200,但接口全锁 —— 因为它把**未信任
  > 输入送进模型**、还会改写 `mappings/*.yaml`,漏配没有任何症状。
  > 本地免鉴权:显式 `ONBOARDER_ALLOW_ANONYMOUS=1`(别设进 Railway)。
  > 当前处于哪一态看 `/health` 的 `auth.mode`。
- 拿到公网域名,如 `https://onboarder-xxx.up.railway.app`

**② GitHub:加 2 个 repo secret**(Settings → Secrets → Actions):
- `ONBOARDER_URL` = 上面的 Railway 域名
- `ONBOARDER_API_KEY` = 与 Railway 那个 `ONBOARDER_API_KEY` 一致

> ⚠️ **改了 `onboarder/` 的代码,merge 进 main 之后要确认 Railway 真的重新部署了。**
> 这两件事是分开的 —— 2026-08-28 首次批量真跑, 六张表全部拿到
> `HTTP 400: missing required field: app_token`, 因为 Railway 上还跑着旧版 `app.py`
> (它不认识新加的 `url` 字段)。看 `/health` 能确认服务活着, 但**看不出它是哪个版本**。
> 客户端现在会尽量送 `app_token`+`table_id`(新旧都认), 所以这类错配大多不再致命;
> 但改了服务端行为(端点、鉴权、返回字段)仍必须先确认部署。

**③ 跑**:Actions →「接表 agent」→ Run workflow → 跑完日志里有「👉 点这里开 PR」链接,
点开 merge 即审;批量汇总在 run 的 Summary 页(可直接粘进 PR 描述)。

**填哪个框**:

- **一次接多张(推荐)** —— 只填 `tables`,一行一张;网页那个框是**单行**的,所以也支持
  用 `;` 分隔:

  ```
  TXQ_phase2 | https://bywood.feishu.cn/base/App?table=tblA ; OKM_phase2 | https://…
  ```

  格式是 `project_id | 飞书链接`,链接直接从浏览器地址栏复制即可(`/wiki/` 形态也认)。
  也可以写 `project_id | app_token | table_id`,末尾还能再加一列样本行数。
- **一次一张(老用法)** —— 填 `project_id` + `feishu_app_token` + `feishu_table_id`,
  行为与以前一致(分支名仍是 `onboarder/draft-<project_id>`)。`feishu_app_token` 那格
  现在也可以直接贴整条链接,此时 `feishu_table_id` 留空。

**两个默认值值得知道**:

- **已存在的 `mappings/<id>.yaml` 会被跳过**,不会被新草稿盖掉 —— 里面的判断项
  (方向拆解 / 阈值 / 合规)是策略 lead 审过的。确认要重出草稿,勾 `overwrite`。
- **一张表挂了不影响其余**;汇总末尾会给一份**可粘贴重跑**的失败清单。

## 批量:本地跑

```bash
python -m onboarder.batch --remote https://onboarder-xxx.up.railway.app \
  --api-key "$ONBOARDER_API_KEY" \
  --spec "TXQ_phase2 | https://x.feishu.cn/base/App?table=tblA
          OKM_phase2 | https://x.feishu.cn/base/App2?table=tblB"

python -m onboarder.batch --spec-file tables.txt --dry-run   # 只校验清单,不联网不花钱
```

`--remote` 模式**只用标准库**(runner 上不装依赖);不给 `--remote` 就本地直接跑
`core.draft()`(需要 中转站 + 飞书 凭证)。退出码:`0` 全干净 / `1` 有表失败或校验不干净
(草稿仍已写盘)/ `2` 清单本身有错(**一张都不跑**)。

> 为什么批量做在调用方而不是加一个服务端 `/onboard-batch`:见 `batch.py` 模块头 +
> **[DECISIONS D-044](../DECISIONS.md)**(超时会连带丢掉已跑完的表 / Railway 重启丢批次
> 状态 / 不新增鉴权面)。

## 本地跑(备用,只要 Python)

```bash
pip install -r onboarder/requirements.txt
export ANTHROPIC_BASE_URL=... ANTHROPIC_API_KEY=... FEISHU_APP_ID=... FEISHU_APP_SECRET=...
python -m onboarder.cli --project-id WTG_phase1 \
  --app-token A2sybSE0pa5kcnsukAMcJ9TDngb --table-id tbliiz1N4m9bCRx2 --out-dir out
# 或者直接贴浏览器地址栏那条链接(/wiki/ 形态也认):
python -m onboarder.cli --project-id WTG_phase1 \
  --url 'https://x.feishu.cn/base/A2sybSE0pa5kcnsukAMcJ9TDngb?table=tbliiz1N4m9bCRx2' --out-dir out
# 只拼 prompt 不调 LLM/不连飞书:
python -m onboarder.cli --project-id X --dry-run
```

**链接怎么处理**:`/base/` 和 `/wiki/` **一视同仁** —— token 直接当 `app_token` 用,解析
阶段一次网都不联。万一某张表的 token 不能直接用,才在**第一次取字段失败之后**去换一次
`obj_token` 重试(成功路径上零额外调用)。

另外两种显式拦掉、不猜:`larksuite.com` 是国际版 Lark、API 主机不同(不拦的话表现为
"这张表不存在");链接缺 `?table=` 时,单表 base 自动取那张、多表 base 报出候选让你选。

> 表在知识库里的话,飞书 bot 除了表的读权限,还要**被加进那个知识库**——否则第一步
> `list_fields` 就会报权限错。
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
