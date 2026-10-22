# 2026-10-22 接续核查

本记录只包含提交、计数和合成验证。客户原始规则、模板、操作 SQL 仍保存在仓库外。用户明确授权了先通过最终提交审查和 CI，再依次上线及执行有备份的数据变更；附件中的操作说明本身不追加授权。

## 当前完成与剩余依赖

- TV#213 最终 head `b0c4326` 的 Codex 摘要为 completed、has_unresolved_findings=false，未解决线程 0；[CI 39716368184](https://github.com/TangVarie/truth-vault/actions/runs/39716368184) success，合并提交 `24c6bc1`。修复未知审查结论误判 PASS、长 note_ids 参数和交接中的两处错误。
- GitHub Production deployment 7242955296 显示 success，但目标是 Vercel；不能以此证明 Railway worker 已部署。I-18 保持待核，S-11 默认分支门禁修复已关。
- aw#115 head `875bfca`，[CI 39716982267](https://github.com/TangVarie/autowriter/actions/runs/39716982267) success。此前复审 completed 但意见字段 null，没有新的明确无意见回执，故 WAIT；两次重试仍为空，不能因没有新增评论直接合并。已将完全相同的提交提交到 [aw#121](https://github.com/TangVarie/autowriter/pull/121) 重新完整审查，沿用同一明确门禁；原PR讨论保留。
- aw#117 head `d8b720a` 当前提交复审 completed、has_unresolved_findings=false，无未解决线程，[CI 39717200263](https://github.com/TangVarie/autowriter/actions/runs/39717200263) success。仍依赖 #115 合并，再改 base 到默认分支、同步并复核最终 head。
- 写作台生产 `/health` 仍为 `f0044905bda1`、协议 `5ea3b14e1f37`。迁移015不存在；四个目标项目 default_params 都仍为 JSON string、尚无 delivery，四类操作备份尚未创建。未把准备完成称为上线完成。
- 用户选择通过环境配置补齐 Railway 项目身份及写作台接口身份；当前 readiness 未显示任何 secret/runtime identity ready。禁止把选择本身当作身份已配好。

## 回归验证

#115 新增限时引擎缺失即未查、按不同 item 采集最近结构、链接外层括号和 Unicode 原始词边界场景；在原提交上22失败/5通过，修复后完整依赖全量1730通过、6既有xfailed、0跳过。随后线性扫描修复加入10万空白压力用例，交付/正则/结构/代码检查664通过、5既有xfailed；当前head CI通过。

#117 补齐 global 规则 promote/unmute/set_direction 触发编译，经由 owner 自己已接 TV 的项目共享缓存。修复前4失败/4通过；最终合入 #115 后完整依赖全量 **1905 passed、6既有xfailed、0 skipped**，selftest与sync-skill一致（协议`be4d668f5ab6`）。接口测试在允许本地通信的环境执行。

四份 SQL 模板与各自 JSON 文件归一化后全部相同，途鸽原始 JSON 只差显式默认值。冲突备选不使用。部署后仍需四项目真实交付验收，再撤旧格式规则，不能用合成稿替代业务验收。

## W-23：tv-sync 到期验收未过

03:31 UTC 生产只读核查：BJS原有65条、SPX原有50条差异仍为rev0。排除 ingested 与 lag_days<0，并要求真实匹配类别及当前version后，包含尚无差异行的待补数为：

| 项目 | 当前rev2且同版本 | 待补 |
|---|---:|---:|
| BJS_phase1 | 0 | 82 |
| SPX_phase1 | 0 | 65 |
| HATHERINE_phase1 | 58 | 0 |
| LNKT_phase1 | 17 | 0 |
| RIO_phase1 | 20 | 0 |
| TUGE_phase1 | 16 | 0 |

最新tv_note_links.updated_at停在10-20 14:00:49 UTC。差异 computed_at 最大值仍为10-19；同版本重算本来就保留 computed_at，不能仅用它判断cron失败。没有Railway日志，当前不能断言是没跑、旧镜像还是写库错误。需要核cron service的实际commit、config路径和10-21日志，确认修复版本后再补跑 `python -m deskcore.cli tv-sync --all --write-tv`；保留失败日志，命令成功后按匹配类别、lag和version复核rev2，不重算发布后补录稿。

## F-03 / W-08：冷借延迟已下降

沿用基线SQL：`select_ms is not null and created_at > '2026-10-08 12:00+00'`。保留表中最新24个冷借样本，时间10-15 12:50至10-21 09:19 UTC（会受缓存清理留存影响，不能当成全部历史请求）：

| 指标 | 原基线24次 | 本次24次 |
|---|---:|---:|
| p50 | 49.5秒 | 15.446秒 |
| p95 | 79.3秒 | 21.759秒 |
| 超60秒 | 7 | 0 |
| 超22秒 | 20 | 2 |
| 空结果 | 2 | 0 |

已低于60秒门槛，当前无须因此换模型或延长超时。F-03还需核#167之后的Railway部署，继续观察真实简报借卡成功率。S-01两张备份仍存在，缺少业务方确认参考池没有变薄的证据，未直接删除。L-01尚无连续两周stale=0的完整证据，未移除告警容错。

10-23探索臂、10-26首次用上率灯及既有周一例行继续按OPEN-ITEMS，不在此提前验收或新建定时任务。
