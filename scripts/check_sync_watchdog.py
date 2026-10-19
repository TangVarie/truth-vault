#!/usr/bin/env python3
"""看门狗自检 (D-073): 把 sync-watchdog.yml 里那段 python 原样抠出来, 喂各种假 API 响应, 看判得对不对。

从 ci.yml 的内联块挪出来(2026-10-19, TV#202): ci.yml 体积闸 G6 到顶了, 规矩是新守卫写成 scripts/ 里的脚本。
在仓根跑: python scripts/check_sync_watchdog.py
"""
import os, pathlib
os.chdir(pathlib.Path(__file__).resolve().parent.parent)   # 下面的相对路径都按仓根
# 看门狗是"没人天天看 Actions"的最后一道; 它自己判错了比没有更坏 ——
# 报绿会让人以为夜跑好着, 而那正是 run #177 丢三步时日志给人的印象。
# 这里把它那段 python 原样抠出来, 喂四种假 API 响应, 看判得对不对。
# 反证: 把 conclusion=="success" 那个判据删掉 → 情形②(全失败)会变成绿, 本步红。
import io, contextlib, json, pathlib, re, textwrap, datetime as dt, yaml

wf = yaml.safe_load(pathlib.Path(".github/workflows/sync-watchdog.yml").read_text(encoding="utf-8"))
steps = [s for s in wf["jobs"]["watch"]["steps"] if s.get("run")]
body = next(s["run"] for s in steps if "WATCHED" in s["run"])
m = re.search(r"python - <<'PY'\n(.*?)\n\s*PY\s*$", body, re.S)
assert m, "抠不出看门狗那段 python —— 改了写法就同步改这条守卫"
src = textwrap.dedent(m.group(1))

def now(h=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
def run_with(responses, error=None, code_src=None):
    """responses: {workflow 文件名: [run dict, ...]}; error 非空则让 API 抛它。
    code_src 不给就跑原样那段。返回 (exit_code, 输出)"""
    class FakeResp:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(self.payload).encode()
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        name = url.split("/workflows/")[1].split("/runs")[0]
        # error 可以是 str(所有都报错) 或 {workflow: 消息}(只打指定的那个)。
        # 上一版只支持"所有都报错", 于是【一个验成了 + 另一个 403】这种最要紧的
        # 组合从没被测到 —— 而那正是 verified==0 兜底【盖不住】403 分支的场合。
        if isinstance(error, dict) and name in error:
            raise RuntimeError(error[name])
        if isinstance(error, str) and error:
            raise RuntimeError(error)
        if name not in responses:
            raise RuntimeError("HTTP Error 404: Not Found")
        return FakeResp({"workflow_runs": responses[name]})
    import urllib.request as ur
    ns = {"__name__": "__main__"}
    buf = io.StringIO(); code = 0
    real = ur.urlopen; ur.urlopen = fake_urlopen
    import os
    old = dict(os.environ)
    os.environ.update(REPO="o/r", GH_TOKEN="x", RUN_URL="http://run")
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code_src or src, "watchdog", "exec"), ns)
    except SystemExit as e:
        code = e.code or 0
    finally:
        ur.urlopen = real
        os.environ.clear(); os.environ.update(old)
    return code, buf.getvalue()

def mkrun(hours_ago, conclusion, status="completed"):
    return {"run_started_at": now(hours_ago), "conclusion": conclusion,
            "status": status, "html_url": "http://x"}
BOTH = ["daily-sync.yml", "features-sync.yml"]

# ① 两趟都有近期成功 → 绿
code, out = run_with({w: [mkrun(5, "success")] for w in BOTH})
assert code == 0, f"① 都成功该绿, 实际 {code}: {out}"
assert "✅" in out, out

# ② 近期跑了但【一趟都没成功】(run #177 那种 cancelled 也在内) → 红
code, out = run_with({"daily-sync.yml": [mkrun(5, "cancelled"), mkrun(29, "success")],
                      "features-sync.yml": [mkrun(5, "success")]})
assert code == 1, f"② 全失败/取消该红, 实际 {code}: {out}"
assert "没有一趟成功" in out, out

# ③ 窗口内【一趟都没有】(cron 没触发 / 被 GitHub 停了) → 红
code, out = run_with({"daily-sync.yml": [mkrun(72, "success")],
                      "features-sync.yml": [mkrun(5, "success")]})
assert code == 1, f"③ cron 没触发该红, 实际 {code}: {out}"
assert "一趟 schedule 都没有" in out, out

# ④ 【从来没跑过】(刚合并的新 workflow) → 不该红, 但要说一声
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")],
                      "features-sync.yml": []})
assert code == 0, f"④ 新 workflow 还没跑过不该红, 实际 {code}: {out}"
assert "还没有过任何 schedule 跑" in out, out

# ⑤ API 查不动(403 改权限 / 502)【不许】读成绿 —— 代班 review on #144 抓到的:
#    原来一个 except Exception 全吞成 note, 于是"一个 workflow 都没验过"会打勾。
# 404(还没进默认分支)是良性的 —— 但只有在【别的 workflow 真查成了】的前提下才放行,
# 否则就落进下面 ⑦ 那条("一个都没真查成")。两者的分界正是这条守卫要钉的。
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")]})   # features 走 404
assert code == 0 and "还没进默认分支" in out, f"404 该放行并说明: {code} {out}"
# 非 404 的错误(403 改权限 / 502)必须判红
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")]},
                     error="HTTP Error 403: Forbidden")
assert code == 1, f"⑤ API 查不动该判红(查不成 ≠ 没问题), 实际 {code}: {out}"
# ⚠️ 判据要钉在【只有这条分支才会打的那句话】上。第一版写的是 `"查不动" in out`,
#    而下面 ⑦ 那条兜底消息里也有"查不动"三个字 —— 于是把 403 误判成良性 404 时,
#    ⑦ 仍然让整体判红、out 里仍然有"查不动", 断言照样过。本 PR 通篇在修
#    "只查字符串在不在", 结果我在断言里又犯一次。改成钉那句独有的话。
assert "看门狗这一趟对它是瞎的" in out, f"403 该走【查不动】那条分支, 实际: {out}"
assert "还没进默认分支" not in out, f"403 不是 404, 不该按良性跳过: {out}"

# ⑥ 还在跑的(conclusion=null)【不许】判成失败 —— cron 漂移 5.5-6.3h + 180min 超时,
#    features-sync 完全可能在看门狗那一刻还没跑完。误报几次之后就没人看这些邮件了。
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")],
                      "features-sync.yml": [mkrun(2, None, status="in_progress")]})
assert code == 0, f"⑥ 还在跑的不该判红, 实际 {code}: {out}"
assert "还在跑" in out, out

# ⑦ 全是"跳过"时不许打勾: 一个都没真查成 = 看门狗等于没跑
code, out = run_with({"daily-sync.yml": [], "features-sync.yml": []})
assert code == 1, f"⑦ 一个都没验成该判红, 实际 {code}: {out}"
assert "一个 workflow 都没真查成" in out, out

# ⑧ 窗口里【同时有"还在跑"和"失败"】: 上一版先判 running 就 continue, 于是那趟失败
#    被整个吞掉、还打勾(代班 review on #145)。失败必须照报。
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")],
                      "features-sync.yml": [mkrun(1, None, status="in_progress"),
                                            mkrun(4, "failure")]})
assert code == 1, f"⑧ 窗口里有失败就该报, 不该被'还在跑'吞掉, 实际 {code}: {out}"
assert "没有一趟成功" in out, out

# ⑨ status 是 pending(不在任何白名单里)也得当"还没跑完", 不许报成失败。
#    判据钉 conclusion is None 才对这个枚举封闭。
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")],
                      "features-sync.yml": [mkrun(1, None, status="pending")]})
assert code == 0, f"⑨ pending 也是没跑完, 不该判红, 实际 {code}: {out}"
assert "还在跑" in out, out

# ⑩ "一个验成了 + 另一个 403": verified==0 那条兜底【盖不住】这种, 403 分支必须自己判红。
code, out = run_with({"daily-sync.yml": [mkrun(5, "success")]},
                     error={"features-sync.yml": "HTTP Error 403: Forbidden"})
assert code == 1, f"⑩ 有一个验成了也不能放过另一个 403, 实际 {code}: {out}"
assert "看门狗这一趟对它是瞎的" in out, out
assert "一个 workflow 都没真查成" not in out, f"⑩ 这次该是 403 分支判的红, 不是兜底: {out}"

# ⑪ 只有"还在跑"的那些不算验过 —— 否则兜底会被它们撑起来而失效。
#    两种"跳过"各测一次: 【从来没跑过】(responses 里是空 list)和【404 还没进默认
#    分支】(responses 里根本没这个 key)。上一版只写了前者, 注释却标着"404 跳过" ——
#    于是 404 那一支要是哪天开始计入 verified, 这条根本发现不了(代班 review on #146)。
code, out = run_with({"daily-sync.yml": [],            # 从来没跑过
                      "features-sync.yml": [mkrun(1, None, status="in_progress")]})
assert code == 1, f"⑪a 没跑过+还在跑 = 一个都没真查成, 该判红, 实际 {code}: {out}"
assert "一个 workflow 都没真查成" in out, out
code, out = run_with({                                  # daily-sync 不在 responses → 404
                      "features-sync.yml": [mkrun(1, None, status="in_progress")]})
assert code == 1, f"⑪b 404跳过+还在跑 也该判红, 实际 {code}: {out}"
assert "一个 workflow 都没真查成" in out, out
assert "还没进默认分支" in out, f"⑪b 该走 404 那一支: {out}"

# ⑫ 季度那趟【过了第一趟该跑的日子还从来没跑过】→ 红; 日子没到 → 只是说明。
#    不钉这条, 季度 cron 一次都没触发时 ④ 那条"新上线放行"会一直放行(Codex on #202)。
both_ok = {w: [mkrun(5, "success")] for w in BOTH}
# 两头都把日子改写掉, 不靠真钟: 不然 2027-01-04 之后 ⑫a 自己就红了(codex review on TV#202)
due_src = src.replace('"2027-01-04"', '"2000-01-01"')
assert due_src != src, "WATCHED 里季度那条的第一趟日子改了 —— 同步改这条守卫"
code, out = run_with({**both_ok, "feature-discovery.yml": []}, code_src=src.replace('"2027-01-04"', '"2999-01-01"'))
assert code == 0 and "还没有过任何 schedule 跑" in out, f"⑫a 第一趟日子没到该放行: {code} {out}"
code, out = run_with({**both_ok, "feature-discovery.yml": []}, code_src=due_src)
assert code == 1 and "该跑过第一趟了" in out, f"⑫b 过了日子还没跑过该红: {code} {out}"
code, out = run_with({**both_ok, "feature-discovery.yml": [mkrun(24 * 30, "success")]},
                     code_src=due_src)
assert code == 0, f"⑫c 季度窗口(93 天)里有一趟成功就该绿: {code} {out}"

print("  ✓ 看门狗自检: 都成功→绿 / 全失败或取消→红 / cron 没触发→红 / 新上线→放行 /"
      " API 查不动→红 / 还在跑→放行 / 一个都没验成→红 / 在跑+失败→照报失败 /"
      " pending→当没跑完 / 单个 403 不被别人验成掩盖 / 在跑的不算验过 / 季度过了日子没跑→红")
