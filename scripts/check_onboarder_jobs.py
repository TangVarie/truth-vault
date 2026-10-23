"""
check_onboarder_jobs.py — onboarder 后台作业 + 轮询 (I-21) 的端到端自检。

2026-10-23 宽表 (XIWU 52 列、百健士 48 列) 起草超过 5 分钟: 服务端跑完、`/onboard`
回了 200, 调用方 (300 秒) 和 Railway 边缘 (~5 分钟) 已经先断了, 结果丢了。现在
每张表是服务端的后台作业 (POST /onboard/jobs → GET /onboard/jobs/<id>), 客户端
onboarder/batch.py 提交后轮询。

这里起一个**真的** onboarder.app (core.draft 换成假的, 不连飞书、不调模型), 前面
挡一个 1 秒就断的假"边缘", 让 batch.main 打它; 再用一台按剧本回包的假作业服务端
走客户端自己的分支 (截断回包、作业中途没了)。每条断言都对着一个会让它变红的
回退版本试过 (见 TV#228)。

D-075: ci.yml 有体积上限 (check_system_map.py G6), 新块直接写成脚本, ci.yml 只留一行调用。

用法 (仓库根或 scripts/ 下都行):
    python scripts/check_onboarder_jobs.py
需要 fastapi + uvicorn (CI 那一步自己装)。退出码 0 = 全过。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import urllib.error as urllib_error
import urllib.request as urllib_request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onboarder import batch, core, links  # noqa: E402

out = Path(tempfile.mkdtemp())


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = batch.main(argv)
    return rc, buf.getvalue()


# ── ④-b 后台作业 + 轮询 (I-21) ──────────────────────────────
#
# 10-23 宽表 (52 / 48 列) 起草超过 5 分钟: 服务端跑完、回了 200, 调用方和
# Railway 边缘已经在 5 分钟处断开, 结果丢了。现在每张表是服务端的后台作业,
# 客户端隔几秒问一次。这里用**真的** onboarder.app (core.draft 换成假的),
# 在本地起一个 uvicorn, 让 batch.main 打它: 判据是"起草比单个请求的超时还长
# 也能拿到结果", 而不是"代码里有 jobs 两个字"。
import time as _t
import socket
import uvicorn
import onboarder.app as OA2

_orig_draft = core.draft
SLOW = {"SLOW_p1": 1.5}                  # 秒; 比下面单次轮询请求的超时长
def _fake_draft(**kw):
    _t.sleep(SLOW.get(kw["project_id"], 0.1))
    if kw["project_id"] == "BAD_p1":
        raise links.LinkError("这个 base 有多张表: tbl1 / tbl2")
    return {"mapping_yaml": f"project_id: {kw['project_id']}\nfield_mapping: {{}}\n",
            "review_brief": "b", "errors": [], "uncovered": [], "pending": [],
            "is_error": False}
core.draft = _fake_draft
os.environ["ONBOARDER_API_KEY"] = "k"
with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0)); _port = _s.getsockname()[1]
_srv = uvicorn.Server(uvicorn.Config(OA2.app, host="127.0.0.1", port=_port,
                                     log_level="warning"))
_srv.install_signal_handlers = lambda: None      # 不在主线程; 旧版 uvicorn 会去装
threading.Thread(target=_srv.run, daemon=True).start()
for _ in range(100):
    if _srv.started: break
    _t.sleep(0.05)
URL2 = f"http://127.0.0.1:{_port}"

# 前面再挡一层假"边缘": 任何一个请求超过 EDGE_S 秒没回就 502 —— 就是 Railway
# 那 ~5 分钟, 按比例缩成 1 秒。客户端只打边缘, 不直接打服务。
from http.server import ThreadingHTTPServer
EDGE_S = 1.0
class Edge(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _fwd(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = urllib_request.Request(
            URL2 + self.path, data=self.rfile.read(n) if n else None, method=self.command,
            headers={k: v for k, v in self.headers.items()
                     if k.lower() in ("content-type", "x-onboarder-key")})
        try:
            with urllib_request.urlopen(req, timeout=EDGE_S) as r:
                code, raw = r.status, r.read()
        except urllib_error.HTTPError as e:
            code, raw = e.code, e.read()
        except Exception:
            code, raw = 502, b'{"detail":"edge: upstream took too long"}'
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)
    do_GET = do_POST = _fwd
_edge = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
threading.Thread(target=_edge.serve_forever, daemon=True).start()
EDGE = f"http://127.0.0.1:{_edge.server_address[1]}"

# 先复现 10-23: 同步 /onboard 穿过边缘, 起草一慢就 502 (服务端其实跑完了)
try:
    batch._call(EDGE, "k", "POST", "/onboard",
                {"project_id": "SLOW_p1", "app_token": "App", "table_id": "tbl1"}, 30)
    raise AssertionError("假边缘没挡住慢请求 —— 下面的断言就测不出东西了")
except batch._HTTPStatus as exc:
    assert exc.code == 502, exc

batch.POLL_INTERVAL, batch.POLL_REQUEST_TIMEOUT = 0.1, 5
shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
rc, log = run(["--spec", "SLOW_p1 | https://x.feishu.cn/base/App?table=tbl1\n"
                         "BAD_p1  | https://x.feishu.cn/base/App?table=tbl2\n"
                         "OK3_p1  | https://x.feishu.cn/base/App?table=tbl3",
               "--remote", EDGE, "--api-key", "k", "--out-dir", str(out), "--timeout", "30"])
assert (out / "SLOW_p1.yaml").exists(), f"起草比边缘的单请求上限长就拿不到结果了:\n{log}"
assert (out / "OK3_p1.yaml").exists() and not (out / "BAD_p1.yaml").exists(), log
assert "退回同步" not in log, "新服务端有 jobs 端点却走了同步 /onboard"
# 断言服务端那句原文 —— "tbl1" 在 SLOW_p1 的链接里本来就有, 不能拿它当证据
assert "HTTP 400: LinkError: 这个 base 有多张表" in log, \
    f"作业里的输入错误没按 400 + 原文报出来:\n{log}"
assert rc == 1, rc
print("  ✓ 同步 /onboard 穿过边缘会 502 (复现 10-23) · 走作业就拿得到结果"
      " · 作业里的 400 原样报出 · 一张失败不带走整批")

# 总等待到点 → 这张失败并说清楚, 不是无限等
SLOW["SLOW_p1"] = 3
shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
rc, log = run(["--spec", "SLOW_p1 | https://x.feishu.cn/base/App?table=tbl1",
               "--remote", EDGE, "--api-key", "k", "--out-dir", str(out), "--timeout", "1"])
assert rc == 1 and "--timeout" in log and not (out / "SLOW_p1.yaml").exists(), log
# 作业丢了 (onboarder 重启) → 404 → 这张失败, 不是一直轮询
try:
    batch._call(URL2, "k", "GET", "/onboard/jobs/nope", None, 1)
    raise AssertionError("不存在的作业没回 404")
except batch._HTTPStatus as exc:
    assert exc.code == 404 and "重启" in str(exc), exc
# 同时在跑的作业有上限 (每个都是一次全表扫描 + 一次 16k 输出)
for _ in range(100):                     # 先等上面超时那张在服务端跑完
    if not any(v["status"] == "running" for v in OA2._JOBS.values()): break
    _t.sleep(0.1)
SLOW["SLOW_p1"] = 2
_H2 = {"X-Onboarder-Key": "k"}
_body = {"project_id": "SLOW_p1", "app_token": "App", "table_id": "tbl1"}
_codes = []
for _ in range(OA2.MAX_RUNNING_JOBS + 1):
    _req = urllib_request.Request(URL2 + "/onboard/jobs", data=json.dumps(_body).encode(),
                                  headers={"Content-Type": "application/json", **_H2},
                                  method="POST")
    try:
        with urllib_request.urlopen(_req, timeout=5) as _r:
            _codes.append(_r.status)
    except urllib_error.HTTPError as _e:
        _codes.append(_e.code)
assert _codes == [202] * OA2.MAX_RUNNING_JOBS + [429], _codes
print("  ✓ 总等待到点 → 失败并提示 --timeout · 作业丢了 → 404 · 同时在跑有上限 (429)")
# 轮询这一侧的两种异常 —— 客户端自己的分支, 上面那台真服务端造不出来:
#   · 回包被截断 (边缘/中间盒提前关了连接, 抛 IncompleteRead, 它不是 OSError)
#     → 算一次瞬时失败, 下一轮照常拿到结果, 不能把这张判死
#   · 作业中途没了 (onboarder 重启/重部署) → 404 → 这张马上失败,
#     不能一直轮询到 --timeout (默认 20 分钟)
SCRIPT = {"TRUNC_p1": ["running", "truncated", "running"],
          "GONE_p1": ["running", "gone"]}
class Jobs(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, truncate=False):
        raw = json.dumps(obj, ensure_ascii=False).encode()   # 和 FastAPI 一样回 UTF-8
        self.send_response(code)
        # 截断: 声明的长度比实际多, 写完就关连接
        self.send_header("Content-Length", str(len(raw) + (64 if truncate else 0)))
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._send(202, {"job_id": json.loads(self.rfile.read(n))["project_id"]})
    def do_GET(self):
        jid = self.path.rsplit("/", 1)[-1]
        step = SCRIPT[jid].pop(0) if SCRIPT[jid] else "done"
        if step == "gone":
            SCRIPT[jid] = ["gone"]           # 没了就一直没了
            self._send(404, {"detail": "没有这个作业: 过期了, 或 onboarder 重启/重部署过"})
        elif step in ("running", "truncated"):
            self._send(200, {"status": "running", "elapsed_s": 1}, truncate=step == "truncated")
        else:
            self._send(200, {"status": "done", "result": {
                "mapping_yaml": f"project_id: {jid}\nfield_mapping: {{}}\n",
                "review_brief": "b", "errors": [], "uncovered": [], "pending": [],
                "is_error": False}})
_js = HTTPServer(("127.0.0.1", 0), Jobs)
threading.Thread(target=_js.serve_forever, daemon=True).start()
shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
_t0 = _t.monotonic()
rc, log = run(["--spec", "TRUNC_p1 | https://x.feishu.cn/base/App?table=tbl1\n"
                         "GONE_p1  | https://x.feishu.cn/base/App?table=tbl2",
               "--remote", f"http://127.0.0.1:{_js.server_address[1]}", "--api-key", "k",
               "--out-dir", str(out), "--timeout", "30"])
_el = _t.monotonic() - _t0
assert (out / "TRUNC_p1.yaml").exists(), f"一次被截断的轮询回包就把这张判死了:\n{log}"
assert not (out / "GONE_p1.yaml").exists() and "HTTP 404" in log and "重启" in log, log
assert rc == 1 and _el < 10, f"作业没了还在轮询 ({_el:.0f}s, rc={rc}):\n{log}"
_js.shutdown()
print("  ✓ 轮询回包被截断 → 下一轮照常拿结果 · 作业中途没了 → 马上失败, 不等到 --timeout")
_edge.shutdown()
_srv.should_exit = True
core.draft = _orig_draft
os.environ.pop("ONBOARDER_API_KEY", None)

shutil.rmtree(out, ignore_errors=True)
print("onboarder 后台作业自检通过")
