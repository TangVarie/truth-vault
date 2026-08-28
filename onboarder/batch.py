"""onboarder/batch.py — 一次接 N 张飞书表(逐表调 /onboard,汇总成一个分支/PR)。

    python -m onboarder.batch --remote https://onboarder-xxx.up.railway.app \\
        --spec "TXQ_phase2 | https://x.feishu.cn/base/App?table=tblA
                OKM_phase2 | https://x.feishu.cn/base/App2?table=tblB"

为什么批量在**调用方**而不是服务端加一个 /onboard-batch:
  ① 单表本来就逼近超时 —— 全表 distinct 扫描 + 16k 输出, 现有 workflow 给的是
     `--max-time 220`。服务端把 N 张串起来必然超, 而超时之后**已经跑完的那几张也
     一起没了**(HTTP 请求是原子的, 没有部分结果)。
  ② Railway 重启/重部署会丢内存里的批次状态 —— 要么加一个 job store, 要么接受
     "批量跑一半没了"。为一年几次的接表加一套作业存储不值。
  ③ 逐表独立请求天然做到"一张挂了不拖垮整批", 且**不新增鉴权面**(SUP-001 那条
     跨服务守卫的用例表不用动)。

两种跑法, 同一套编排:
  · --remote <url> : 打 Railway 的 /onboard(GH Actions 走这条 —— 它连得上 Railway,
                     连不上中转站)。**只用标准库**, runner 上不需要装任何依赖。
  · 不给 --remote  : 本地直接调 core.draft(需要 中转站 + 飞书 凭证 + onboarder 依赖)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import links

# 逐表的 HTTP 超时(秒)。单表 = 全表 distinct 扫描 + 一次 16k 输出的 LLM 调用;
# 现有单表 workflow 给 220s, 大表偏紧 —— 批量这边放宽到 300s 并可 --timeout 调。
DEFAULT_TIMEOUT = 300

STATUS_ICON = {"ok": "✅", "needs_fix": "⚠️", "failed": "❌", "skipped": "⏭️"}


# ── 逐表起草 ────────────────────────────────────────────────────────────────

def _post_onboard(base_url: str, api_key: str | None, payload: dict, timeout: int) -> dict:
    """POST <base>/onboard。只用标准库 —— runner 上不装依赖(见模块头 ②)。"""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/onboard",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"X-Onboarder-Key": api_key} if api_key else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:800]
        except Exception:  # noqa: BLE001  —— 读不出响应体不该盖掉原始状态码
            pass
        raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连不上 {base_url}: {exc.reason}") from exc


def _draft_one(entry: dict, *, remote: str | None, api_key: str | None,
               sample_n: int, model: str | None, timeout: int) -> dict:
    payload: dict[str, Any] = {"project_id": entry["project_id"],
                               "sample_n": entry.get("sample_n") or sample_n}
    for k in ("url", "app_token", "table_id"):
        if entry.get(k):
            payload[k] = entry[k]
    if model:
        payload["model"] = model

    if remote:
        return _post_onboard(remote, api_key, payload, timeout)

    # 本地模式才 import core —— 它拉 yaml/anthropic/requests, 而 --remote 那条路
    # 在 GH runner 上跑, 不该为此装一堆依赖。
    from . import core
    return core.draft(
        project_id=payload["project_id"],
        app_token=payload.get("app_token"),
        table_id=payload.get("table_id"),
        url=payload.get("url"),
        sample_n=payload["sample_n"],
        model=model or core.DEFAULT_MODEL,
    )


def _ref_of(entry: dict) -> str:
    return entry.get("url") or f"{entry.get('app_token')}/{entry.get('table_id')}"


# ── 编排 ────────────────────────────────────────────────────────────────────

def run_batch(
    entries: list[dict],
    *,
    out_dir: str = "mappings",
    remote: str | None = None,
    api_key: str | None = None,
    sample_n: int = 30,
    model: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    overwrite: bool = False,
) -> list[dict]:
    """逐表起草 + 写盘。一张失败不影响其余;返回逐表结果。

    **串行**, 不并发:每张表都要全表扫一遍飞书 + 打一次中转站。并发省下的是几分钟,
    换来的是飞书限流和网关并发上限这两类"只在批量大的时候才出现"的故障 —— 而批量
    大正是它最不该挂的时候。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for i, entry in enumerate(entries, start=1):
        pid = entry["project_id"]
        yaml_path = out / f"{pid}.yaml"
        brief_path = out / f"{pid}.brief.md"
        head = f"[{i}/{len(entries)}] {pid}"

        # ⚠️ 占位检查在**花钱之前**。这一条是防 mapping 被悄悄覆盖:mappings/*.yaml
        #    里的判断项(方向拆解/阈值/合规)是策略 lead 审过的, 重跑一版新草稿盖上去
        #    = 把人拍过的板悄悄换成模型的猜测, 而 diff 里它长得就像一次正常更新。
        #    放在起草前还顺手省掉一次全表扫描 + 一次 LLM 调用。
        if yaml_path.exists() and not overwrite:
            print(f"{head}: ⏭️  已存在 {yaml_path} —— 跳过。里面的判断项(方向拆解/阈值/合规)"
                  "可能已被策略 lead 审过,不自动覆盖;确认要重出草稿再加 --overwrite")
            results.append({
                "project_id": pid, "status": "skipped", "ref": _ref_of(entry),
                # 这条会进 markdown 表格单元格 —— 保持一行、短。完整解释在上面的日志里。
                "detail": "已存在,未覆盖(要重出草稿加 `--overwrite`)",
                "errors": [], "uncovered": [], "pending": [], "files": [],
            })
            continue

        print(f"{head}: 起草中… ({_ref_of(entry)})")
        try:
            res = _draft_one(entry, remote=remote, api_key=api_key,
                             sample_n=sample_n, model=model, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 —— 一张表的任何失败都不该带走整批
            print(f"{head}: ❌ {exc}")
            results.append({
                "project_id": pid, "status": "failed", "ref": _ref_of(entry),
                "detail": str(exc), "errors": [], "uncovered": [], "pending": [], "files": [],
            })
            continue

        if not res.get("mapping_yaml"):
            detail = res.get("reason") or "模型没产出可解析的 mapping"
            print(f"{head}: ❌ {detail}")
            results.append({
                "project_id": pid, "status": "failed", "ref": _ref_of(entry),
                "detail": detail, "errors": [], "uncovered": [], "pending": [], "files": [],
            })
            continue

        yaml_path.write_text(res["mapping_yaml"], encoding="utf-8")
        brief_path.write_text(res.get("review_brief") or "", encoding="utf-8")
        status = "needs_fix" if res.get("is_error") else "ok"
        print(f"{head}: {STATUS_ICON[status]} 写出 {yaml_path.name} + {brief_path.name}"
              f" · errors={len(res.get('errors') or [])}"
              f" uncovered={len(res.get('uncovered') or [])}"
              f" 待确认={len(res.get('pending') or [])}")
        results.append({
            "project_id": pid, "status": status, "ref": _ref_of(entry), "detail": "",
            "errors": list(res.get("errors") or []),
            "uncovered": list(res.get("uncovered") or []),
            "pending": list(res.get("pending") or []),
            "app_token": res.get("app_token"), "table_id": res.get("table_id"),
            "files": [str(yaml_path), str(brief_path)],
        })

    return results


def _cell(text: str, limit: int = 120) -> str:
    """任意文本 → 能安全放进 markdown 表格单元格的一行。

    detail 里装的是**异常消息**(HTTP 响应体 / 飞书报错 / 路径), 里面出现 ``|`` 或
    换行是常事 —— 原样塞进单元格会把整张表撑烂, 而表格正是这份汇总唯一"一眼能看完"
    的部分。截断也必要:一段 800 字的 HTTP 响应体会把那一行推到屏幕外。完整内容在
    下面的分节里。
    """
    one = " ".join((text or "").split()).replace("|", "\\|")
    return one if len(one) <= limit else one[: limit - 1] + "…"


def render_summary(results: list[dict]) -> str:
    """批量结果 → markdown(PR 描述 / GH step summary / 终端都用这一份)。"""
    n = {k: sum(1 for r in results if r["status"] == k)
         for k in ("ok", "needs_fix", "failed", "skipped")}
    lines = [
        "## 批量接表结果",
        "",
        f"共 {len(results)} 张:✅ {n['ok']} 通过 · ⚠️ {n['needs_fix']} 需修 · "
        f"❌ {n['failed']} 失败 · ⏭️ {n['skipped']} 跳过",
        "",
        "| 表 | 状态 | 词表 errors | 未覆盖列 (D-021) | 待确认 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        detail = f" {_cell(r['detail'])}" if r["status"] in ("failed", "skipped") else ""
        lines.append(
            f"| `{r['project_id']}` | {STATUS_ICON[r['status']]} {r['status']}{detail} "
            f"| {len(r['errors'])} | {len(r['uncovered'])} | {len(r['pending'])} |"
        )

    problems = [r for r in results if r["errors"] or r["uncovered"]]
    if problems:
        lines += ["", "### 需要修的(合 PR 前)", ""]
        for r in problems:
            lines.append(f"**{r['project_id']}**")
            for e in r["errors"]:
                lines.append(f"- 词表:{e}")
            if r["uncovered"]:
                lines.append(
                    f"- 未覆盖列(D-021,会整行进 quarantine):{', '.join(r['uncovered'])}"
                )
            lines.append("")

    # 失败项直接给一份**可粘贴重跑**的清单 —— 比"自动重试"有用:批量失败几乎都是
    # 权限/链接/表本身的问题, 重试一万次还是同一个错, 而每次重试都是一次全表扫描。
    retry = [r for r in results if r["status"] == "failed"]
    if retry:
        lines += ["", "### 重跑这几张(修好原因后原样粘回 tables 输入)", "", "```"]
        lines += [f"{r['project_id']} | {r['ref']}" for r in retry]
        lines += ["```", ""]
        for r in retry:
            lines.append(f"- `{r['project_id']}`: {r['detail']}")

    lines += [
        "",
        "### 下一步",
        "",
        "1. 审 `mappings/<id>.brief.md` —— 只列要策略 lead 拍板的项(方向拆解 / tier 阈值 / 合规)。",
        "2. 把 yaml 里的 `[待确认]` 填成实值(`intent_override` 例外:不确定就删掉该键或写 null)。",
        "3. `python scripts/preflight_mapping.py <project_id>` 拉活表体检,按结果校正 mapping。",
        "4. merge 后跑一次 `Daily TV sync` 验证真导入。",
    ]
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _read_spec(args) -> str:
    if args.spec_file:
        return Path(args.spec_file).read_text(encoding="utf-8")
    return args.spec or ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="批量接表:一次把 N 张飞书表起草成 mappings/<id>.yaml 草稿",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="清单格式(一行一张,也可用 ; 分隔;# 后为注释):\n"
               "  TXQ_phase2 | https://x.feishu.cn/base/App?table=tblA\n"
               "  OKM_phase2 | AppToken | tblB | 50\n",
    )
    p.add_argument("--spec", default="", help="批量清单(行/分号分隔)")
    p.add_argument("--spec-file", default="", help="从文件读清单(与 --spec 二选一)")
    p.add_argument("--remote", default=os.environ.get("ONBOARDER_URL", ""),
                   help="Railway onboarder 地址;不给则本地直接跑 core.draft")
    p.add_argument("--api-key", default=os.environ.get("ONBOARDER_API_KEY", ""),
                   help="X-Onboarder-Key(默认取环境变量 ONBOARDER_API_KEY)")
    p.add_argument("--out-dir", default="mappings", help="草稿输出目录")
    p.add_argument("--sample-n", type=int, default=30, help="每张表拉多少行文案样本")
    p.add_argument("--model", default="", help="覆盖模型(默认服务端 ONBOARDER_MODEL)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="逐表 HTTP 超时(秒)")
    p.add_argument("--overwrite", action="store_true",
                   help="允许覆盖已存在的 mappings/<id>.yaml(默认跳过 —— 那里面有人审过的判断项)")
    p.add_argument("--summary-file", default="", help="把 markdown 汇总另存一份(PR 描述用)")
    p.add_argument("--dry-run", action="store_true",
                   help="只解析清单并打印计划,不联网、不花钱")
    args = p.parse_args(argv)

    entries, errors = links.parse_batch_spec(_read_spec(args))
    if errors:
        print("❌ 清单有问题,整批不跑(先修清单):", file=sys.stderr)
        for e in errors:
            print("   · " + e, file=sys.stderr)
        # 清单错 = 人打字的问题, 一条都不跑。跑一半再报错会留下"部分接进来了"的
        # 中间态, 而这个中间态要靠人去分辨哪几张成了。
        return 2

    print(f"── 批量接表:{len(entries)} 张 ──")
    for e in entries:
        print(f"   · {e['project_id']}  ←  {_ref_of(e)}")
    if args.dry_run:
        print("\n(--dry-run:只解析清单,未联网)")
        return 0

    if args.remote and not args.api_key:
        # 服务端 fail-closed(SUP-001):没带 key 会**每张表都** 401。与其跑一轮
        # 全 401, 不如现在就说清楚。
        print("⚠️  --remote 模式没给 --api-key / ONBOARDER_API_KEY —— "
              "服务端鉴权是 fail-closed 的,大概率每张都 401。", file=sys.stderr)

    results = run_batch(
        entries,
        out_dir=args.out_dir,
        remote=args.remote or None,
        api_key=args.api_key or None,
        sample_n=args.sample_n,
        model=args.model or None,
        timeout=args.timeout,
        overwrite=args.overwrite,
    )

    summary = render_summary(results)
    print("\n" + summary)
    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")

    # 退出码:有任何一张没干净通过就非 0。草稿照样已经写盘(调用方该先推分支再看
    # 退出码), 让 run 变红是为了"别直接 merge", 不是为了丢掉产出。
    bad = [r for r in results if r["status"] != "ok"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
