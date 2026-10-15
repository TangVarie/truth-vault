# 10-13/14 Daily TV sync 重复失败修复

两天的每日同步均在 `feishu_sync`、`essence_sync` 判红；watchdog 是前者失败引发的派生告警。故障早于 TV#181/Jev#12 合并，合并后 CI 正常。

- SPX 飞书列「互动量」已改名为「互动数」。mapping 同时兼容旧名与新名；两列共存按已有引擎的映射顺序以新名为准（含0和空值），断源检查按同一目标列聚合，任一源名存在即可。仍写 `notes.interactions` 和指标快照；不改变以 `comments_count` 判爆的规则。生产只读核查：535 条笔记、507 个新列数值；其中 7 条标准指标待补正（5 空、2 旧）。其余既有标准值多数保留。
- HATHERINE 的模型响应是合法 JSON 数组；校验器直接 `.get()`，未进入既有重试/失败队列，提前中断项目。新增顶层对象、essence 对象、标量闭集和列表成员类型检查，错误结构按内容校验失败重试；仍无效的单条进入 failed_queue，继续处理后续笔记，不猜数组第一项或改标注词表。诊断时 282 篇、275 已标、7 待标。

离线回归覆盖新名/旧名/双列（含0与空值）及千分位写入标准列和快照、错误结构后重试成功、两次结构错误进失败队列并继续后续笔记。既有词表、重试/失败队列与写入大小上限检查通过。模型和正常 API/卫生失败告警保持原规则。

恢复须在修复代码上定向同步 SPX、只续作 HATHERINE 缺失项，回读核查指标一致及待标数，不全量重标。正常定时运行成功后 watchdog 自然恢复；手动成功不冒充 schedule 成功。新40条复核仍进行中，标签未冻结，评论候选不追加试跑、不启用评论工具。

故障证据：[10-13 Daily](https://github.com/TangVarie/truth-vault/actions/runs/38375968103)、[10-14 Daily](https://github.com/TangVarie/truth-vault/actions/runs/38529381244)、[10-14 watchdog](https://github.com/TangVarie/truth-vault/actions/runs/38499459709)。生产恢复结果见下节。

## 已执行恢复与10-15定时观察

PR182已合并`bc81c7bf`，PR及main的Python/SQL/mapping CI通过。SPX定向同步 [38542412990](https://github.com/TangVarie/truth-vault/actions/runs/38542412990)成功：540篇同步、535快照、errors=0；7条标准指标及其最新快照回读全部匹配，原27条认领隔离保留。HATHERINE pending续标 [38542417239](https://github.com/TangVarie/truth-vault/actions/runs/38542417239)成功：7次调用/7篇完成/0失败，282/282已标；原275篇完整行摘要执行前后均为`f9adb93217cc1a88fc42b33603d000de`，未重标。

无写入预检38542036132核心列/指标检查通过，但dry-run按旧逻辑不读认领名单，27条旧隔离仍计错；真实同步读名单后成功。这条历史红run不表示兼容修复失败。

截至10-15 12:04（北京时间），当日Daily schedule尚未出现，workflow active。09:48 watchdog [38667591742](https://github.com/TangVarie/truth-vault/actions/runs/38667591742)只检查26小时内schedule，仍指向10-14修复前run38529381244；手动定向成功不等于全量schedule成功。最新特征层schedule38608278755成功。下一位继续观察首次修复后全量定时，再核watchdog，不能改成计入部分手动跑来清红。
