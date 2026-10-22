# 2026-10-21 接续记录

本记录区分代码验证、生产只读核查与待部署步骤。客户原文、答卷、规则和操作包不进入仓库。

## 当前主线

- aw#115：基线 c709793 的五条新审查意见已修复并推到 095d223；完整依赖环境 1704 passed、6 个既有 xfailed、0 skipped，skill 和自检通过。
- aw#117：基线 52eca1b 的七条新审查意见已修复，并集成 #115 修复，推到 7d73278；全量 1872 passed、6 个既有 xfailed、0 skipped，skill 和自检通过。49a3684 的回归回放到修复前为 11 失败、4 个对照参数通过，修复后通过。
- 两个 PR 的已修意见线程已解决，均已重新进入对当前 head 的远端审查。CI 分别为 [39572085478](https://github.com/TangVarie/autowriter/actions/runs/39572085478) 和 [39572230602](https://github.com/TangVarie/autowriter/actions/runs/39572230602)，均 success。最终能否合并仍看最新 head 审查结果。
- 写作台生产仍是 f0044905bda1 / 协议 5ea3b14e1f37，未部署 #115/#117。生产 rule_compiles 表不存在，迁移 015 仍待 #117 上线前执行。
- Jev 的编题接口、编题 key 和评论开关正常；写作台与 Jev 的 148 条合成正则放行/拒绝对拍差异为 0，Jev 无须再改安全闸。

代码细节和回归证据见 [aw 接续审查记录](https://github.com/TangVarie/autowriter/blob/claude/aw-e-check-rules/docs/review-2026-10-21.md)。

## I-16 / G-03：首夜只读核查

10-21 Daily [39563186123](https://github.com/TangVarie/truth-vault/actions/runs/39563186123) 于 07:36–08:12 UTC（北京时间 15:36–16:12）成功完成。按 docs/d122-repair/05_after_nightly.sql 的同一口径核：

- 08:34 UTC：受保护列非空转 NULL 0 次；emotional_lever 有值但 content_format 为空 0 篇；恢复计划 1,102 格无再次置空、无改成其他值。
- 新版 essence-v1-93035a562b2e 有 106 行，应打分 106 篇、缺分 0；原 80 篇全部已重打；XIWU_phase2 使用 pooled 切点 0 篇；日志 GATE3_SCORE_CHECK_DONE rc=0。
- 旧版 essence-v1-322f02c9465f 仍 80 行，backup_content_scores_d122_20261020 不存在。清理未执行，不能把新版重打完成当成旧分清理完成。

与前夜 [39387004722](https://github.com/TangVarie/truth-vault/actions/runs/39387004722) 对照，11 个每日项目的 upserted 规模相近，全部 errors=0。计数来自各项目日志的 Done 行，不含客户原文。

| 项目 | 10-20 upserted | 10-21 upserted | 10-21 errors |
|---|---:|---:|---:|
| ANSHEN_phase1 | 201 | 201 | 0 |
| BJS_phase1 | 240 | 244 | 0 |
| HATHERINE_phase1 | 300 | 307 | 0 |
| LNKT_phase1 | 374 | 374 | 0 |
| OKMAN_phase1 | 346 | 346 | 0 |
| RIO_phase1 | 796 | 796 | 0 |
| SPX_phase1 | 570 | 590 | 0 |
| TUGE_phase1 | 169 | 174 | 0 |
| WTG_phase1 | 710 | 710 | 0 |
| XIWU_phase1 | 301 | 301 | 0 |
| XIWU_phase2 | 102 | 107 | 0 |

## I-18：长 note_ids 参数

修复前 200 个合成 id 拼接参数在 Path.exists 处复现 OSError errno 36。改为 is_file，并仅捕获 ENAMETOOLONG；权限、I/O 等其它路径错误及正常文件的读取错误仍上抛。8/200 个 id、文件、去重、空白及 EACCES/EIO 场景已加入 check_feature_orchestration.py；编排和 worker 端点检查通过。该修复需本 PR 合并、worker 部署后生效，OPEN-ITEMS 保持待上线。

## 接下来按依赖推进

1. #115 最新提交过审后合并并核生产 build、协议 895ed01874d6；按仓库外操作包先模板、再真实交付批次、再退路/撤旧规则、再补代码检查。五份模板均通过本地校验，但冲突的途鸽备选仍不使用。
2. #115 合并后将 #117 改 base 到默认分支并同步，再核最终 head 的测试和审查；迁移 015 先于部署。#117 协议为 be4d668f5ab6。
3. D-123 旧分清理仍按已备好的带锁、备份和行数守卫 SQL 执行。该步骤尚未写生产。
4. 北京时间 10-21 22:40（14:40 UTC）核第一次新时段 tv-sync：无 23502、computed_at 前进、BJS/SPX 可比较对子 diff_rev=2。当前仍未到这个检查时间，不提前报验收。
5. 10-22 的备份、借卡延迟和 stale 灯检查，10-23 的探索臂检查，仍按 OPEN-ITEMS；既有周一 routine 保留。


## 合并前复核更正

09:05 UTC：#115 摘要为当前 head、completed，但 has_unresolved_findings 为 null，且没有新的无意见回执。原 codex_gate.py 用真假判断将 null 当作 False，错误打印 PASS；合并前的独立复核拦住了它，未执行合并。本 PR 将未知字段、缺失字段和非布尔值都改为 WAIT，增加离线回归并接入 CI。#117 本轮复审新增 unmute 激活路径意见，也继续修复。#212 的两条意见一并修正：首夜 invariant 必须严格为零；#211 包含可执行 SQL 和门禁代码，不能称纯文档或视为已审查。用户已明确授权后续有备份的数据变更和上线；授权仍以最终 head 的有效审查与 CI 通过为前提。

## 10-22 复审接续

#115 复审新增四项、#117 新增 global 激活编译路径，均继续修复后再审，尚未合并。#213 的路径异常处理已收窄到 ENAMETOOLONG；新增 EACCES/EIO 反证，修复前能复现静默成功，修复后编排、worker 端点、19 个合并门禁场景及系统地图六条守卫全部通过。

上文“未到 10-21 14:40”的表述为 10-21 当时快照，10-22 接续时该检查已经到期；需读取实际运行和数据库结果后更新 W-23，不能沿用旧快照作结论。生产授权持续有效，仍须最终提交审查和 CI 通过后按顺序执行。
