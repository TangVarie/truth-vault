"""worker — Railway 批量 LLM worker(essence 标注 + flywheel 策展)。

为什么独立成包:essence/curate 是批量 LLM 任务,本来在 daily-sync(GitHub Actions)里
直接跑 scripts/*.py,但 GitHub 海外 runner 连不上中转站(网络层 connect=0)→ 步骤失败。
搬到 Railway(连得上网关)后,由 GitHub daily-sync 调本服务端点触发,保留 GitHub 的
"失败→邮件"告警(D-038 收尾 / docs/17 §7-D)。
"""
