# 三仓接手执行书 · 2026-10-22

> **10-23 更新：** 本文是 10-22 的快照。A（#121 部署）、B（模板 + 015）、C（#117 合并上线，`e3bc3fb`）、§8 W-23 补算都已完成；D 等真实交付。现状看 [OPEN-ITEMS](../OPEN-ITEMS.md) 顶部，下面「#117 open」「015 未应用」等描述已过时。

这份文件交给下一位实际接手的人。事实核查窗口为 **北京时间 10-22 11:55–11:59（03:55–03:59 UTC）**；操作前重新读当前线上和 PR，不能把本快照当成持续监控。本轮按用户要求转为交接，**没有继续部署或执行生产数据写入**。此前证据见 [10-22接续记录](continuation-2026-10-22.md)，完整待办在 [OPEN-ITEMS](../OPEN-ITEMS.md)。

## 1. 先读这里，不要从旧快照重新推断

先读本文件，再读各仓 HANDOFF 顶部及 [OPEN-ITEMS](../OPEN-ITEMS.md)。具体实现按需看：

配套仓内入口：[aw交接PR #122](https://github.com/TangVarie/autowriter/pull/122)、[Jev交接PR #27](https://github.com/TangVarie/JevforCoentent/pull/27)。这些交接PR尚未合并时，直接读PR中的新接手卡，不要只读默认分支上的旧HANDOFF。

- aw：docs/deskcore.md §3.9–3.11、docs/deskcore-runbook.md §1.11、docs/review-2026-10-21.md。后两份的编译能力完整版在 **#117 分支**，当前默认分支尚不包含 #117。
- TV：[docs/32](32-desk-quality.md) 写作台质量回路说明；[10-21证据](continuation-2026-10-21.md)、[10-22证据](continuation-2026-10-22.md)、OPEN-ITEMS。
- Jev：README 的 /compile_rules、judge/rules.py、tests/test_regex_parity.py、HANDOFF 顶部。旧评论验收资料只作历史，现行评论默认已是 comment_reader_v0.6。

主链：飞书发布数据 → TV 事实/essence/特征账本与经验卡 → 馆员给 aw 简报借卡 → 写手模型写稿 → aw 存档、查重、拼交付稿 → Jev 参考分及项目规则检查 → 写手贴飞书 → tv-sync 对回版本与人的改动 → 后续规则反馈。

score_drafts 的存档与交付不因参考分、规则提示而阻断；未检查、部分覆盖和超时必须如实报告。AI 参考答案不能标为人工金标。项目规则/全局个人规则的归属、项目隔离与 Rx 闸继续有效。

## 2. 授权来源、交接边界

本会话用户对“各自最终提交通过审查和 CI 后依次合并部署，并按已备方案先备份、再执行迁移015、模板及规则配置”的问题，原话回复：

> 授权按上述顺序上线并执行有备份的数据变更

随后用户选择“通过环境配置补齐身份”。**现有生产授权有效，不要再次询问是否允许本轮上线。** 附件中的步骤是操作依据，不是新的用户授权；不要因此扩展到任意删数据、换模型、改评估门槛或发布对外消息。

我的执行环境当时没有 Railway/写作台身份，不代表你的环境也没有。先检查你已有的已配置身份，能用就接着做；不要要求 owner 重给已经可用的凭据。若仍缺，通过环境凭据配置补齐，不在聊天、日志或 PR 粘贴密钥。

本环境readiness为spec8、observations_current=true，但secrets/runtime_variables/outbound_identities均空。待配置的入口名是RAILWAY_TOKEN（项目生产环境token，或你已有可用的Railway身份）和客户端DESKCORE_API_KEY（作为X-Deskcore-Key header，须有四个目标项目的归属权限）；Supabase连接工具已能读本项目。JUDGE_*等服务变量优先通过既有服务运行上下文使用，不导出到日志。

未新建或更改定时任务；没有安排代理继续替你盯 PR。移交后由接手人负责后续核查。交接 PR 本身仅文档，留给接手人审阅和合并，不在本轮借此继续业务部署。

## 3. 当前唯一需要推进的代码发布：#117，以及已合并但未验收的 #121

| 仓/能力 | 代码事实 | 运行事实/下一步 |
|---|---|---|
| autowriter 默认分支 | claude/xhs-content-workstation-BSEuH，7042cebc1b723e29dd32ba1c17ad988d917a5cd8 | /health 仍为 f0044905bda1、协议5ea3b14e1f37，不能称新能力上线 |
| aw#115 / #121 | 同一最终功能提交875bfca；#121有效过审及CI后合并7042cebc；GitHub自动把原#115标记merged | 排查并确认 Railway web 和每日cron实际部署 |
| aw#117 | **open，未合并**；head fdeaa9f72cac193fa04201e8c466342e6fd569ba；base已改为默认分支 | 最终head审查completed / has_unresolved_findings=false，未解决线程0，CI39718629002 success；先完成前置部署、015和关闭自动补编 |
| truth-vault 默认分支 | cf34c354a517e6337151e29b6bec4da732d8c10c；#213合并24c6bc1，#214合并cf34c35 | GitHub Production成功指向Vercel，**不证明Railway worker已部署**；I-18仍待运行版本确认 |
| Jev main | e00c183（#26交接PR已合并）；本轮没有改服务实现 | /health：comment_tools_enabled=true、write_enabled=true、compile.key=true、compile.model=claude-sonnet-5-5、writer_keys=2 |

生产数据库：Supabase 项目 kduysqedrclrfevrxiie。只读回查：
- autowriter.rule_compiles 不存在，即015未应用。
- backup_delivery_params_20261020、backup_format_rules_20261020、backup_rule_payloads_20261020、backup_fallback_rules_20261020 均不存在。
- 四项目 default_params 仍是 JSON string，尚无 delivery。**备份、模板、退路/撤旧、手设代码检查均未执行。**
- 四份模板 SQL 与 JSON 文件归一化结果全部一致；TUGE 原始 JSON 仅显式默认字段有差别。Postgres只读模拟合并得到4行，存储形状/其它字段/目标模板三个断言均true；该模拟不是写入。

已完成代码回执：
- #121：[CI39718161474](https://github.com/TangVarie/autowriter/actions/runs/39718161474)；合并提交push CI39718489765也成功。
- #117：[CI39718629002](https://github.com/TangVarie/autowriter/actions/runs/39718629002)。
- TV#213：[CI39716368184](https://github.com/TangVarie/truth-vault/actions/runs/39716368184)；TV#214：[CI39719021520](https://github.com/TangVarie/truth-vault/actions/runs/39719021520)。

## 4. 已修过的事，不要重做或回退

**#115/#121**：版本自身时间切最近60天、按项目过滤并排除补录；按不同item收候选，避免数百个修订版本挤掉其它稿；交付与查规则共用规范化标题/实际正文；正则源码双方同限300字；regex限时引擎缺失时报告未查，禁止无时限re回退；中文URL fragment与URL内平衡括号保留、外层右括号结束URL；长分隔符扫描保持线性；禁词边界根据原始字符决定，修复ß/ſ/K；异常tags容器和成员进入problems。

**#117**：手设检查独立计数；排队判定真正起跑时重算共同截止；全部未判题计入汇总；坏题、重复题、空题库及部分覆盖显式未查，不能称“守住”；promote/unmute/生效规则改方向立即补编，global规则经owner已接TV的项目共用缓存；doctor权限问题指向015；CI装FastAPI/MCP后重跑全量并拒绝缺依赖跳过。#119是另一处相同方向的CI工作，本轮未修改，不要直接把它也视为已合并。

**TV#213**：Codex门禁只接受显式布尔false；null/缺失/非布尔、过期提交、伪造作者和失败API均WAIT；19个离线场景接入CI。长note_ids只捕获ENAMETOOLONG，其它路径权限/I/O错误上抛。修正首夜invariant必须严格0，以及旧TV#211含可执行SQL/代码、并非纯文档的错误描述。

本地证据：#115完整依赖全量1730 passed / 6既有xfailed / 0 skipped；线性扫描补充后相关664 passed / 5既有xfailed。#117最终功能集 **1905 passed / 6既有xfailed / 0 skipped**；selftest与sync-skill一致，协议be4d668f5ab6。148个合成正则与Jev放行/拒绝对拍差异0。默认沙箱的网络限制会使最小FastAPI TestClient挂起，允许本地接口通信后正常；没有以跳过接口测试替代验证。不要因纯文档交接重复整套业务测试，改实现后再按变更验证。

## 5. 合并门禁：仍按最终提交核

用TV默认分支 scripts/codex_gate.py 核当前head，此外单独检查CI和未解决review线程。三个条件缺一不可：
1. bot的当前head审查completed，has_unresolved_findings严格为false；
2. 当前head的必需CI成功；
3. 无未解决意见。合并时传expected_head_sha，head变动就重新核。

原#115在875bfca两次返回completed + null，没有新的明确无意见回执，未按它合并。将**完全相同提交**放到新#121重新完整审查，取得completed/false、CI和0线程后才合并。不要重新打开旧PR，也不要把null当作通过。#117若又被改head，旧fdeaa9f回执不能沿用。

## 6. 拿到运行入口后，按这个顺序推进

### A. 先确认#121实际部署

aw Railway目标已由历史deployment7203205490确认：
- project：8d2ffc90-ba7c-4e73-a7b3-248d85f0f4c3
- production environment：e0a1aa51-d015-440d-9d67-a5c0b665bc42
- [项目入口](https://railway.com/project/8d2ffc90-ba7c-4e73-a7b3-248d85f0f4c3?environmentId=e0a1aa51-d015-440d-9d67-a5c0b665bc42)

先识别deskcore web与tv-sync cron各自service ID，核实际commit、分支、config路径、watch规则和日志。web配置deskcore/railway.json；cron配置deskcore/railway.cron.json、UTC14:00（北京22:00）、tv-sync --all --write-tv。TV worker/librarian是另外的服务，不能拿web/Vercel状态代替。

~~~bash
railway status --project 8d2ffc90-ba7c-4e73-a7b3-248d85f0f4c3 --environment e0a1aa51-d015-440d-9d67-a5c0b665bc42 --json
curl --fail --silent --show-error https://autowriter-production.up.railway.app/health
~~~

不要输出变量列表或令牌。Railway redeploy默认重用旧镜像，需要更新源码时明确使用已核实的 --commit 7042cebc1b723e29dd32ba1c17ad988d917a5cd8，或核清source后 --from-source。先读失败原因，再决定重试，不能只循环重部署。

成功条件：运行build对应7042cebc或包含它的已核实后续提交，协议895ed01874d6，健康配置正常；另核cron是否包含#116的computed_at修复。当前没有Railway日志，尚不能断言旧版本是自动部署没触发、旧镜像还是构建失败。

### B. 备份、015与四个模板

#121部署确认后，先按私有操作包建模板备份4行，备份表启用RLS并撤销anon/authenticated访问，再回读。后续DDL用apply_migration，数据DO用execute_sql；读取执行的SQL前自己审一遍，不盲目执行整个目录。

015取自**#117最终分支** migrations/015_rule_compiles.sql，必须早于#117部署：新缓存表主键(memory_id,sha)、result JSONB、memory外键ON DELETE CASCADE、仅服务使用、RLS开启；检查实际GRANT与RLS。迁移本身不需要旧缓存数据备份，因为本快照表尚不存在；若现在已存在，先核结构与权限，不覆盖同事的新工作。

模板按原包 templates/PLAN.md §A：bjs.json、xiwu.json、hatherine.json、**tuge.json**。不要使用冲突备选tuge_published_block.json，也不要把SQL与CLI两路各跑一次。SQL备份后以旧default_params完全匹配作守卫，写JSON string内的delivery，保持其它字段。预期4行，话题配额8/5/4/5，Hatherine原有5个isolation_terms保留。私有拆分脚本templates-4.sql是有守卫回滚，不是下一个正向步骤。

模板先完成配置回读和已有合成验证；真实四项目交付验收仍须做，未验收前保留旧格式规则。#117发布可以在保留旧规则期间推进，不必为了撤规则制造假业务批次。

### C. 再上线#117并补编

已完成改base和同步，不要再把它当作叠在旧#115分支的PR。操作前复查当前head，先在web服务设RULE_COMPILE_AUTO=0并确认生效，避免CLI和服务各编一遍付两份钱。015确认可访问后，按门禁合并#117，核实际build及协议be4d668f5ab6。

在有对应服务既有变量的运行环境，先数再真编：
~~~bash
python -m deskcore.cli compile-rules --all --dry-run
python -m deskcore.cli compile-rules --all
~~~
不要加--force。dry-run也要JUDGE_URL/JUDGE_API_KEY及TV映射；缺映射/出境口径/超时不是“缓存已齐”。一次CLI中global按(id,sha)去重；“池子”合计按项目重复，“要编”才是本次要发送数量。整批超时不要立刻重复付费发起。核成功缓存和未编原因后，恢复服务自动补编，再做带X-Deskcore-Key的open_project、score_drafts、check_rules实际验收；凭据用header，不放URL。检查hard/soft/拿不准/未查、保存版本归属、交付文本与实际检查对象一致。写手skill协议需同步到be4d668f5ab6。

### D. 四项目真实交付通过后，再退路/撤旧/代码检查

每项目一批真实稿，回包delivery.text正确、problems合理；只读预演或合成稿不能代替这一步。按私有README继续：
1. W28.md W1：先建立带RLS的插入日志，插3条hard退路，核文本摘要和归属；各项目open_project看得到退路。
2. PLAN §B备份6条旧格式规则；真正退役使用 **W28.md的W2 DO**，它比旧PLAN多模板与退路守卫。只降candidate，不删。不要误跑拆分脚本format-rules-1.sql的旧版DO。
3. 保留Hatherine D1–D7及拆分候选，本轮不顺手重录。
4. APPLY.sql只处理ec0b9bd6，先备份1条、核摘要/状态/严重性与模板守卫，再应用和回读；不把PAYLOADS里其它候选一起录。

任何备份表已存在、预期行数不符或CAS不匹配，先查现在状态，不能drop备份、重建覆盖或强行继续。进度只把计数/id前缀写到OPEN-ITEMS的W-28/J-15。

## 7. 回滚入口

保留实际部署commit、操作前值、执行时间和各步回读。#117运行回退优先回已验收的#121版本，先关闭自动补编，保留缓存与015表，不自动DROP表。若要连#121也回到旧服务，先评估已撤格式规则并按带守卫的规则回滚恢复，再切服务，防止交付指引消失。

模板回滚按PLAN §A：只在delivery仍等于本次写入时移除该键，保留之后修改的其它字段。W1回滚按W28，只撤日志记录且未改动的本次插入；W2恢复按备份/当前状态守卫。ec0b9bd6按APPLY.sql对应回滚段，不用整个旧行覆盖之后的人工作业。先确认正向步骤确实执行过，不把rollback文件整批运行。

## 8. W-23：已经到期，接手后优先补跑

03:31 UTC核查：原有BJS65条、SPX50条差异仍rev0；含尚无差异行的真实可比较对子，**BJS待82，SPX待65，共147**。最新link更新时间10-20 14:00:49 UTC，另四个项目当前口径111条。下面查询只输出计数，不含客户稿：

~~~sql
SELECT l.tv_project_id,
       count(*) FILTER (WHERE d.diff_rev=2 AND d.version_id=l.version_id) AS current_rows,
       count(*) FILTER (WHERE coalesce(d.diff_rev,0)<2
                         OR d.version_id IS DISTINCT FROM l.version_id) AS pending_rows
FROM autowriter.tv_note_links l
LEFT JOIN autowriter.tv_edit_diffs d USING(note_id)
WHERE l.version_id IS NOT NULL
  AND l.match_kind IN ('body_exact','title_exact','fuzzy','edited','tv_lineage')
  AND (l.lag_days IS NULL OR l.lag_days>=0)
GROUP BY 1 ORDER BY 1;
~~~

先读10-21 cron日志，核代码/退出码，再在正确服务变量和含修复代码下补跑：
~~~bash
python -m deskcore.cli tv-sync --all --write-tv
~~~
日志如要求先补指纹，先补对应指纹再重跑，别盲目循环。验收是可比较对子同版本rev2、无23502，排除ingested和lag<0；**同版本重算本来保留computed_at**，不能要求每条时间都前进。I-18要另核TV worker部署含24c6bc1的代码，Vercel成功不是证据。

## 9. 其它到期事项：带着证据接，不扩大本轮操作包

- D-122首夜已核：恢复1102格无漂移、受保护列非空转NULL为0；emotional_lever有值但content_format空为0。任何非零都查，不能以新笔记豁免。旧BUG已修，不要重跑恢复覆盖后来人工修改。
- D-123：新scorer essence-v1-93035a562b2e 已106/106、应打缺0，原80篇均重打；旧版322f02c9465f仍80行，其备份/清理未执行。另有docs/d122-repair/d123_gate3_rescore.sql；不能把新版完成当成旧分清理完成，也别与015/模板操作混跑，先审其备份权限、锁和行数守卫。
- F-03/W-08：保留冷借样本24，p50=15.446秒、p95=21.759秒、超60秒0、超22秒2、空0；原基线49.5/79.3秒。缓存会清理，不代表全部历史；仍核#167后的Railway部署和真实简报成功率，当前不因此换模型/延长超时。
- S-01：两张10-08备份到期但未删，先确认“参考池没变薄”的业务前置。L-01：没有连续两周stale=0的完整证据，未去掉||true。
- **北京10-23** G-05探索臂：10-16 14:00 UTC起的deskcore批次，核arm约15%、arm_source、mixed标记及未标mixed的item；TV缓存library_version带:dl/:explore/:ext。
- **北京10-26** 首次DESK_USE_RATE_CHECK_DONE灯，按OPEN-ITEMS检查真实稿与漏账、当前diff_rev口径；既有周一例行保留。不要因看到旧“10-21 14:40未到”重新等过期时间。
- 评论线已开、C4=v0.6；不重新做旧C3/C4验收、不拿AI答案补人工。Gate2 combo未过，不升L2；项目层通配已清，Rx闸仍在。Jev本轮不需要为了aw执行期限时改实现。

## 10. 私有材料与本地工作区

**给接手人的私有补充包**：与本文件一同交付handoff-private-2026-10-22.tar.gz，包内README和SHA256SUMS解释来源/脚本映射；只有owner与接手人之间传，不上传GitHub、PR、仓库或公开存储。包不含密钥，包含原始ops-packets-2026-10-21.tar.gz及本轮整理的SQL与执行记录；不要把其中任何文件当成已执行回执。

同一环境的原始路径：
- /workspace/attachments/2e5b631b-3b5e-40a6-adf6-e2ea63e208f5/ops-packets-2026-10-21.tar.gz
- /workspace/attachments/ops-packets-2026-10-21/：原包解压目录
- /workspace/operations/20261022/：STATUS.md、RAILWAY-EXECUTION.md及拆分脚本；**脚本都未执行过生产写入**
- /workspace/worktrees/aw-117：功能工作树，fdeaa9f；其它handoff工作树只改文档。
- /workspace/worktrees/aw115-before、aw117-before 是故意覆盖新测试的反证工作树，可能dirty；不是待交付代码，不要push、合并或“修干净”。
- /tmp/ops-20261022-venv、测试日志和临时CLI可能随环境重启丢失；另一环境重新装锁文件及dev、deskcore接口依赖。不要把原始陈旧checkout的HEAD当当前远端。
- 官方Railway CLI 5.71.0在/workspace/operations/bin/railway；发布包SHA256=2e682fd2ddf8d6fdf9e46d9d99d99646ff0022a6abb0c2bca93011348a269fb9，已与官方release asset digest核验。无需携带node_modules或整个venv。

私有脚本索引：templates-0只读、1备份、2应用、3回读、4回滚；format-rules-0备份、1是**不要用于退役的旧DO**、2恢复；w28-0含前置/建日志/插入/回读，w28-1回滚，w28-2为正确退役DO，3/4/5为核查。ec0b9bd6完整APPLY.sql仍在原包，不在拆分目录。任何混合DDL+DML文件先按原说明分步处理，不能for循环跑所有.sql。

## 11. 每完成一步留下什么

在OPEN-ITEMS对应行和新的接续记录写：操作时刻、最终head、审查/CI号、实际运行build/协议、备份表/行数、数据回读及失败原因。不写客户原文，不将“已merge”“计划做”“脚本已备好”当“生产已验收”。下一条摘要应先说明#121部署、#117发布/编译、四项目真实交付、147条补算各到哪一步。
