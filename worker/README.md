# worker · Railway 批量 LLM worker(essence 标注 + flywheel 策展)

> D-038 收尾 / docs/17 §7-D。把 essence/curate 从 GitHub Actions 搬到 Railway —— 因为
> GitHub 海外 runner 连不上中转站(网络层 `connect=0`),而 Railway 连得上(同 librarian/onboarder)。

## 它是什么

一个 FastAPI 服务,**subprocess 跑现有的、已验证的** `scripts/annotate_essence_pass.py` 和
`scripts/curate_flywheel_lessons.py` —— 不重写标注/策展逻辑,只换运行环境(Railway 连得上网关)。
GitHub 的 `daily-sync.yml` 仍是调度器,只是这两步改成 **curl 调本服务**(保留 GitHub 的"失败→邮件"告警)。

```
GitHub daily-sync(cron)
  ├─ 飞书→TV / comments / ssll(通道1)/ prepublish   ← 仍在 GitHub 直跑(不需要网关)
  └─ essence / curate                                  ← curl → Railway worker(连得上网关)跑 LLM
```

## 端点

| 方法 | 路径 | body | 说明 |
|---|---|---|---|
| GET | `/health` | — | Railway healthcheck → `{"ok":true,"service":"tv-worker"}` |
| POST | `/annotate-essence` | `{project, limit?=50, dry_run?, reannotate?}` | 跑 essence Mode A 标注(per project) |
| POST | `/curate` | `{project?, limit?=50, dry_run?}` | 把合格爆款策展成经验卡(喂馆员书架) |

返回 `200 + {ok, returncode, stdout_tail, stderr_tail, action, project}`。`returncode!=0` → `ok=false`,
由 daily-sync 判该步失败。鉴权:设了 `WORKER_API_KEY` 则请求须带 header `X-Worker-Key`;没设则放行(dev)。

## 部署(Railway · 新建第三个 service,与 librarian/onboarder 并存)

1. New service → 连本 repo;Settings → **Config file 指到 `/worker/railway.json`**(root = repo 根,让 subprocess 找得到 `scripts/`)。
2. 配 env:
   - `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`(service_role,绕 RLS 读写 truth_vault)
   - `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` ← **能跑通的那条通道**(同 librarian/onboarder,别用挂掉的组)
   - `ESSENCE_MODEL`(可选,默认 `claude-sonnet-4-6`)
   - `WORKER_API_KEY`(自定口令,建议设 = GitHub `WORKER_API_KEY` secret)
   - `WORKER_RUN_TIMEOUT_S`(可选,单次 subprocess 硬超时,默认 900)
3. GitHub repo secrets 加:`WORKER_URL`(Railway 域名)、`WORKER_API_KEY`(= Railway 那个)。
4. daily-sync 的 essence/curate 步骤 **gate 在 `WORKER_URL != ''`** —— 不配则优雅跳过(绿);配了才真跑。

> ⚠️ 配完 worker 后,GitHub 上的 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` 就**不再需要**了
> (essence/curate 的 LLM 调用已搬到 Railway)。删掉它们可避免有人误以为 GitHub 还在直跑 LLM。
> daily-sync 之前的"红"正是因为 GitHub 配了 `ANTHROPIC_API_KEY` → essence/curate 真跑 → 连不上网关。

## 已知坑 / 运维(2026-06-04 首次上线实测)

1. **中转站余额不足 → 403 `insufficient balance`**:essence/curate 是真花钱的 LLM 调用。
   余额用光时,脚本会收到 `PermissionDeniedError 403 insufficient balance`,该步报 `ok=false`,
   daily-sync 标红。**处置:给中转站账号/token 充值,或换一条有余额的通道**。跟代码无关。

2. **长任务必须在线程池跑(已修)**:`_run` 是阻塞的 `subprocess.run`。它**必须经
   `run_in_threadpool`**(app.py 已这么做),否则一次几分钟的 essence 会**堵死 asyncio
   事件循环 → `/health` 失联 → Railway 健康检查超时把容器重启 → 杀掉本次 run**
   (首版 bug:50 条/轮在 ~301s 被重启,只标了 23 条)。

3. **WORKER_LIMIT 与节奏**:worker 同步跑、跑完才回。默认 `WORKER_LIMIT=15`(实测 ~13s/条,
   约 200s/轮),跑不完下轮 cron 续(脚本按 `essence_annotated_at IS NULL` 续、幂等)。
   backfill 想快:在 GitHub repo **Variables** 把 `WORKER_LIMIT` 调大(单次受 daily-sync 的
   `curl --max-time 900s` 约束,≈ 60 条上限);或手动多跑几轮 `Run workflow`。

## 本地自测

```bash
# dry-run 不调 LLM、不写库(脚本 --dry-run)
curl -s -X POST localhost:8000/annotate-essence -H 'content-type: application/json' \
  -d '{"project":"WTG_phase1","limit":5,"dry_run":true}' | jq
curl -s -X POST localhost:8000/curate -H 'content-type: application/json' \
  -d '{"project":"WTG_phase1","limit":5,"dry_run":true}' | jq
```
