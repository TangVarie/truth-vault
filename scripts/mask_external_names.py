#!/usr/bin/env python3
"""
mask_external_names.py
═══════════════════════════════════════════════════════════════════════════

外部帖 (truth_vault.external_notes) 的品牌 / 产品名遮挡词 → truth_vault.external_note_masks (D-140; schemas/notes_v1_24)。

为什么: 外部参考书架以前只收 Jev 分诊判了「没带产品」的帖, 拿它代替「正文里没有别家品牌名」(D-117)。分诊只看标题和约 60 字
摘要, 11-03 核查 994 篇「没带产品」里 482 篇正文点了产品。owner 11-03:「直接判断就好了吧, 判断哪些属于产品名, 哪些属于内容,
我们要学的不就是内容的写法吗…不用管产品是什么」。所以:
  · 模型【只列词】: 每篇里指向具体品牌、产品系列 / 型号、店铺 / 门店、售卖机构 / 公司的专有名称, 按原文逐字照抄。
    品类词 / 成分词 (按摩椅、痘痘贴、藻油、DHA、能量胶、鼻炎喷雾、通用药品成分名)、人名、地名、话题里的通用词不列;
  · 代码只留在这一篇「标题 + 换行 + 正文」里逐字出现的词 (librarian/external.clean_terms, 和上架时替换同一个口径), 去重,
    整篇一行 upsert 进遮挡表 (空列表也写 = 查过了、没有要遮的)。模型从不改写正文, 替换是馆员上架时代码做的;
  · text_sha = sha256(标题 + 换行 + 正文): 没有遮挡行、或原文变了 (text_sha 对不上) 的才送去列, 列过的不再花钱。

模型: 环境变量 MASK_MODEL, 默认 claude-haiku-5-5 (本仓的小模型)。调用走 annotate_essence_pass.call_claude
(ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL 中转站, 瞬时错误自带重试)。一次送 --batch 篇 (默认 8), 要严格 JSON。
回的不是 JSON / 形状不对, 或回到一半被 max_tokens 截断 (stop_reason; 小模型默认带思考, 思考也占 max_tokens) →
先把这一批对半拆开重列, 拆到一篇还不行才跳过、记一次错 (日志带 stop_reason), 下一晚重列 —— 不会因为同一批 8 篇
每晚一起截断而永远列不上; 回里漏了某篇 → 那篇不写、下一晚重列。
连着 3 批调用本身失败 (余额 / 鉴权 / 中转站挂了) → 这一晚不再往下调。

灯 (docs/29 登记, advisory, 不拖红): 末行哨兵 EXTERNAL_MASK_CHECK_DONE rc=<码>; daily-sync 靠有没有这一行判崩溃。
  rc=0 列完 (或没有要列的; 拆批重列成功不算失败);
  rc=1 有批次失败 (调用失败 / 拆到一篇还回的不是 JSON / 漏篇 / 写库失败), 没列完的下一晚接着;
  rc=2 判不了: 遮挡表还没建 (owner 没跑 v1_24) / 读不了外部表 / 没有 ANTHROPIC_API_KEY。
倒数第二行打用量: 调用次数、输入 / 输出 token, 按标价估的美元数 (中转站实价可能不同)。

用法:
    python mask_external_names.py [--limit 1500] [--batch 8] [--max-minutes 25] [--dry-run]
    python mask_external_names.py --selftest      # CI: 假模型、假库, 不连网
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from librarian import external as X  # noqa: E402

SENTINEL = "EXTERNAL_MASK_CHECK_DONE"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_LIMIT = 1500        # 第一晚把现有的约 1,419 篇一次列完 (11-03)
DEFAULT_BATCH = 8
DEFAULT_MAX_MINUTES = 25    # 到点不再开新批 (夜跑总时长有灯盯着, D-073); 没列完的下一晚接着
MAX_TOKENS = 8000           # 一批 8 篇的词表 + 小模型默认带的思考 (思考也占 max_tokens); 还是截断了就拆批重列
MAX_CONSECUTIVE_API_FAILS = 3
PAGE = 1000
UPSERT_CHUNK = 100
# 标价 (美元 / 百万 token, 输入, 输出)。只用来打估算那一行; 中转站实价可能不同。
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}

SYSTEM = """你帮我们给小红书笔记做「品牌名遮挡」的第一步: 只列出名字, 不改写任何内容。

对每一篇笔记, 列出标题和正文里【指向某个具体对象】的专有名称:
  · 品牌名 (含英文名、简称、昵称式的品牌叫法);
  · 产品系列名、型号名 (如某个系列、某个型号编号);
  · 店铺 / 门店 / 旗舰店名;
  · 售卖机构、公司、服务机构名。
不要列:
  · 品类词和通用名: 按摩椅、痘痘贴、藻油、DHA、能量胶、鼻炎喷雾、益生菌、蛋白粉、留学中介 这类;
  · 通用的成分名、药品通用名、营养素名;
  · 人名、网名、地名、学校名、医院科室这类不是在卖东西的名字;
  · 话题标签里的通用词; 小红书 / 抖音 这类发帖平台本身。
规则:
  · 每个名字按原文【逐字】照抄 (大小写、空格、符号都和原文一样), 不翻译、不补全、不解释; 原文里出现几种写法就列几种;
  · k 填「品牌」或「产品」: 品牌 / 店铺 / 机构 / 公司填「品牌」, 产品系列 / 型号填「产品」;
  · 拿不准算不算的, 列上 (多遮一个词只是读起来别扭, 漏一个就把别家的名字带出去了)。
只输出一个 JSON 对象, 不要任何别的文字, 不要代码块:
{"notes": [{"id": "<笔记编号>", "names": [{"t": "<原文逐字>", "k": "品牌"}]}]}
每篇笔记都要出现一次; 没有要列的, names 写 []。"""


def note_text(row: dict) -> str:
    return f"{row.get('title') or ''}\n{row.get('body') or ''}"


def pending(notes: list[dict], masks: dict[str, str]) -> list[dict]:
    """没有遮挡行、或原文变了 (text_sha 对不上) 的外部帖, 最近抓到的排前面 (书架只看最近 45 天, 先列它们)。纯函数。
    ``masks``: {note_id: text_sha}。"""
    todo = [n for n in notes if n.get("note_id")
            and masks.get(str(n["note_id"])) != X.mask_text_sha(n.get("title"), n.get("body"))]
    todo.sort(key=lambda n: str(n.get("note_id")))
    todo.sort(key=lambda n: str(n.get("fetched_at") or ""), reverse=True)
    return todo


def build_prompt(batch: list[dict]) -> str:
    parts = [f"下面 {len(batch)} 篇笔记, 编号 n1–n{len(batch)}。"]
    for i, n in enumerate(batch, 1):
        parts.append(f'<note id="n{i}">\n{note_text(n)}\n</note>')
    return "\n\n".join(parts)


def parse_reply(raw: str, batch: list[dict]) -> Optional[dict[str, list]]:
    """模型回的 → {note_id: 原始词表}。不是 JSON / 顶层形状不对 → None (这一批跳过)。编号不认识的条目丢掉;
    回里漏了的篇不在结果里 (不写, 下一晚重列)。纯函数。"""
    from annotate_essence_pass import parse_claude_json
    data = parse_claude_json(raw or "")
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        return None
    ids = {f"n{i}": str(n["note_id"]) for i, n in enumerate(batch, 1)}
    out: dict[str, list] = {}
    for item in data["notes"]:
        if not isinstance(item, dict) or not isinstance(item.get("names"), list):
            continue
        nid = ids.get(str(item.get("id") or "").strip())
        if nid is not None and nid not in out:
            out[nid] = item["names"]
    return out


def mask_rows(batch: list[dict], got: dict[str, list], model: str, now_iso: str) -> list[dict]:
    """解析出来的词表 → 要写的遮挡行: 词过一遍 clean_terms (只留原文里逐字出现的、去重)。回里漏了的篇不出行。"""
    rows = []
    for n in batch:
        nid = str(n["note_id"])
        if nid not in got:
            continue
        rows.append({"note_id": nid, "terms": X.clean_terms(got[nid], note_text(n)),
                     "text_sha": X.mask_text_sha(n.get("title"), n.get("body")), "model": model, "masked_at": now_iso})
    return rows


def _missing_table(exc: BaseException) -> bool:
    return X._missing_table(exc)


def fetch_notes(sb) -> list[dict]:
    out, off = [], 0
    while True:
        rows = (sb.schema("truth_vault").table("external_notes").select("note_id, title, body, fetched_at")
                .order("note_id").range(off, off + PAGE - 1).execute()).data or []
        if not rows:
            return out
        out += rows
        off += len(rows)


def fetch_mask_shas(sb) -> dict[str, str]:
    out, off = {}, 0
    while True:
        rows = (sb.schema("truth_vault").table(X.MASK_TABLE).select("note_id, text_sha")
                .order("note_id").range(off, off + PAGE - 1).execute()).data or []
        if not rows:
            return out
        out.update({str(r["note_id"]): r.get("text_sha") for r in rows})
        off += len(rows)


def upsert(sb, rows: list[dict]) -> None:
    for i in range(0, len(rows), UPSERT_CHUNK):
        sb.schema("truth_vault").table(X.MASK_TABLE).upsert(rows[i:i + UPSERT_CHUNK], on_conflict="note_id").execute()


def _reply(r) -> tuple[str, Optional[str]]:
    """``ask`` 回的: (原文, stop_reason) 或只有原文 (selftest 的假模型)。"""
    if isinstance(r, tuple):
        return str(r[0] or ""), (r[1] if len(r) > 1 else None)
    return str(r or ""), None


def run(sb, ask: Callable[[str], object], *, model: str, limit: int, batch_size: int, dry_run: bool,
        max_seconds: float, clock: Callable[[], float] = time.monotonic) -> tuple[int, dict]:
    """主流程。``ask(prompt) -> (模型回的原文, stop_reason)`` 或只回原文 (真跑是 call_claude, selftest 是假的)。
    返回 (rc, 统计)。不抛。回的不是要的 JSON 或被 max_tokens 截断: 对半拆开重列, 拆到一篇还不行才算一次错。"""
    st = {"notes": 0, "todo": 0, "sent": 0, "written": 0, "with_terms": 0, "terms": 0, "batches": 0,
          "api_errors": 0, "junk": 0, "missing": 0, "write_errors": 0, "left": 0, "splits": 0}
    try:
        masks = fetch_mask_shas(sb)
    except Exception as exc:  # noqa: BLE001
        if _missing_table(exc):
            print("  遮挡表 truth_vault.external_note_masks 还没建 (owner 在 SQL editor 跑 schemas/notes_v1_24 之前都是这样), "
                  "这一晚不列; 馆员那边外部卡只给结构")
        else:
            print(f"  ⚠️  读不了遮挡表: {type(exc).__name__}: {str(exc)[:200]}")
        return 2, st
    try:
        notes = fetch_notes(sb)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  读不了外部表: {type(exc).__name__}: {str(exc)[:200]}")
        return 2, st
    st["notes"] = len(notes)
    todo = pending(notes, masks)
    st["todo"] = len(todo)
    todo, st["left"] = todo[:max(limit, 0)], max(len(todo) - max(limit, 0), 0)
    t0, fails = clock(), 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        if clock() - t0 > max_seconds:
            st["left"] += len(todo) - i
            print(f"  到了 {max_seconds / 60:.0f} 分钟, 不再开新批; 还剩 {len(todo) - i} 篇下一晚接着")
            break
        if fails >= MAX_CONSECUTIVE_API_FAILS:
            st["left"] += len(todo) - i
            print(f"  连着 {fails} 批调用失败 (余额 / 鉴权 / 中转站?), 这一晚不再往下调; 还剩 {len(todo) - i} 篇")
            break
        st["batches"] += 1
        st["sent"] += len(batch)
        parts = [batch]
        while parts and fails < MAX_CONSECUTIVE_API_FAILS:
            part = parts.pop(0)
            try:
                raw, stop = _reply(ask(build_prompt(part)))
            except Exception as exc:  # noqa: BLE001 —— 调用失败: 记一次, 下一晚重列
                st["api_errors"] += 1
                fails += 1
                print(f"  ⚠️  第 {st['batches']} 批调用失败: {type(exc).__name__}: {str(exc)[:160]}")
                continue
            fails = 0
            got = None if stop == "max_tokens" else parse_reply(raw, part)
            if got is None:
                why = "回到一半被 max_tokens 截断" if stop == "max_tokens" else "回的不是要的 JSON"
                if len(part) > 1:
                    half = len(part) // 2
                    parts[:0] = [part[:half], part[half:]]
                    st["splits"] += 1
                    print(f"  第 {st['batches']} 批 ({len(part)} 篇) {why}, 拆成 {half} + {len(part) - half} 篇重列")
                    continue
                st["junk"] += 1
                print(f"  ⚠️  第 {st['batches']} 批拆到一篇还{why} (stop_reason={stop}), 跳过 (下一晚重列): "
                      f"{raw[:120]!r}")
                continue
            rows = mask_rows(part, got, model, now_iso)
            st["missing"] += len(part) - len(rows)
            if dry_run:
                st["written"] += len(rows)
            else:
                try:
                    upsert(sb, rows)
                    st["written"] += len(rows)
                except Exception as exc:  # noqa: BLE001
                    st["write_errors"] += 1
                    print(f"  ⚠️  第 {st['batches']} 批写库失败: {type(exc).__name__}: {str(exc)[:160]}")
                    continue
            st["with_terms"] += sum(1 for r in rows if r["terms"])
            st["terms"] += sum(len(r["terms"]) for r in rows)
    bad = st["api_errors"] + st["junk"] + st["write_errors"] + (1 if st["missing"] else 0)
    return (1 if bad else 0), st


def usage_line(model: str) -> str:
    try:
        from annotate_essence_pass import prompt_cache_summary
        u = prompt_cache_summary()
    except Exception:  # noqa: BLE001
        return "用量: 读不到"
    tin = u["input"] + u["cache_write"] + u["cache_read"]
    line = f"用量: 调用 {u['calls']} 次 · 输入 {tin:,} tokens · 输出 {u['output']:,} tokens"
    price = PRICES.get(model)
    if price:
        line += f" · 按标价约 ${tin / 1e6 * price[0] + u['output'] / 1e6 * price[1]:.3f} (中转站实价可能不同)"
    return line


# ── selftest ─────────────────────────────────────────────────────────────
class _Q:
    def __init__(self, db, table):
        self.db, self.t, self.rng, self.up = db, table, None, None

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, a, b):
        self.rng = (a, b)
        return self

    def upsert(self, rows, on_conflict=None):
        self.up = rows
        return self

    def execute(self):
        tab = self.db.tables.get(self.t)
        if isinstance(tab, Exception):
            raise tab
        if self.up is not None:
            if self.db.fail_writes:
                raise RuntimeError("write failed")
            for r in self.up:
                tab[:] = [x for x in tab if x["note_id"] != r["note_id"]] + [dict(r)]
            return type("R", (), {"data": self.up})()
        rows = sorted(tab, key=lambda r: str(r["note_id"]))
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        return type("R", (), {"data": [dict(r) for r in rows]})()


class _DB:
    def __init__(self, tables, fail_writes=False):
        self.tables, self.fail_writes = tables, fail_writes

    def schema(self, s):
        return self

    def table(self, t):
        return _Q(self, t)


def _selftest_stop_reason() -> None:
    """call_claude(meta=...) 把 stop_reason 带出来 (假 anthropic 模块, 不连网); 不给 meta 行为不变。"""
    import types
    import annotate_essence_pass as E

    class _Messages:
        def create(self, **kw):
            assert kw["max_tokens"] == MAX_TOKENS and kw.get("system") == "S", kw
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text='{"notes": [')],
                                         usage=None, stop_reason="max_tokens")
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kw: types.SimpleNamespace(messages=_Messages())
    real = sys.modules.get("anthropic")
    sys.modules["anthropic"] = fake
    try:
        meta: dict = {}
        assert E.call_claude("p", "m", cached_system="S", max_tokens=MAX_TOKENS, meta=meta) == '{"notes": ['
        assert meta == {"stop_reason": "max_tokens"}, meta
        assert E.call_claude("p", "m", cached_system="S", max_tokens=MAX_TOKENS) == '{"notes": ['
    finally:
        if real is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = real


def selftest() -> int:
    notes = [
        {"note_id": "e1", "title": "鼻子又罢工了", "body": "后来换了某某喷雾 X1 系列, 药店说 BrandX 也行。HA 也有人推", "fetched_at": "2026-11-03"},
        {"note_id": "e2", "title": "按摩椅值不值", "body": "看了一圈按摩椅, 家里老人腰不好", "fetched_at": "2026-11-02"},
        {"note_id": "e3", "title": "求推荐", "body": "藻油 DHA 怎么选", "fetched_at": "2026-11-01"},
    ]
    # ① 逐字核对: 模型列的词不在原文里 (改写过的 / 编的) 丢掉; 重复的去重; k 认不得的当品牌; 短拉丁词按词边界
    good = json.dumps({"notes": [
        {"id": "n1", "names": [{"t": "某某喷雾", "k": "品牌"}, {"t": "X1 系列", "k": "产品"}, {"t": "brandx", "k": "公司"},
                               {"t": "BrandX", "k": "品牌"}, {"t": "某某牌", "k": "品牌"}, {"t": "喷", "k": "品牌"},
                               {"t": "HA", "k": "品牌"}]},
        {"id": "n2", "names": []},
        {"id": "n9", "names": [{"t": "按摩椅", "k": "产品"}]},          # 编号不认识: 丢掉
    ]}, ensure_ascii=False)
    got = parse_reply(good, notes[:3])
    assert set(got) == {"e1", "e2"}, "回里漏了 n3: 那篇不写; 不认识的编号丢掉"
    rows = mask_rows(notes[:3], got, "m", "t")
    t1 = rows[0]["terms"]
    assert [x["t"] for x in t1] == ["某某喷雾", "X1 系列", "brandx", "HA"], t1
    assert t1[2]["k"] == "品牌", "k 认不得的当品牌 (多遮不漏)"
    assert rows[1]["terms"] == [] and rows[1]["text_sha"] == X.mask_text_sha(notes[1]["title"], notes[1]["body"]), \
        "空列表也写 = 查过了"
    masked = X.apply_mask(f"{notes[0]['title']} {notes[0]['body']}", t1, {"mask_terms": []})
    assert "某某喷雾" not in masked and "BrandX" not in masked and "X1 系列" not in masked and "HA" not in masked, masked
    assert masked == "鼻子又罢工了 后来换了某品牌 某产品, 药店说 某品牌 也行。某品牌 也有人推", masked
    assert X.apply_mask("haha 真好用", [{"t": "HA", "k": "品牌"}], None) == "haha 真好用", "短拉丁词不换掉单词里的半截"
    assert X.clean_terms([{"t": "ha", "k": "品牌"}], "hahaha") == [], "短拉丁词在原文里只是半截 → 不算出现过"
    sz = X.clean_terms([{"t": "Straße", "k": "品牌"}], "Straße牌")
    assert sz and X.apply_mask("Straße牌", sz, None) == "某品牌牌", "核过的词一定换得掉 (ß 这类 casefold 会变样的字)"
    # ② 垃圾回复: 不是 JSON / 形状不对 → None, 那一批跳过、计一次错, 不崩
    for junk in ("我觉得这篇没有品牌", "```json\n{\"notes\": \"x\"}\n```", "[]", "", "{\"notes\": [{\"id\": \"n1\"}]}"):
        g = parse_reply(junk, notes[:1])
        assert g is None or g == {}, (junk, g)
    # ③ 端到端 (假库): 第一次三篇都列; 正文改了的那篇第二次重列, 没改的不再送; 垃圾回复 rc=1、那批不写
    db = _DB({"external_notes": [dict(n) for n in notes], X.MASK_TABLE: []})
    sent: list = []

    def ask_ok(prompt):
        k = prompt.count("<note id=")
        sent.append(k)
        return json.dumps({"notes": [{"id": f"n{i}", "names": [{"t": "BrandX", "k": "品牌"}]} for i in range(1, k + 1)]})
    rc, st = run(db, ask_ok, model="m", limit=10, batch_size=2, dry_run=False, max_seconds=60)
    assert rc == 0 and st["written"] == 3 and sent == [2, 1] and len(db.tables[X.MASK_TABLE]) == 3, (rc, st, sent)
    assert [r["terms"] for r in sorted(db.tables[X.MASK_TABLE], key=lambda r: r["note_id"])] == \
        [[{"t": "BrandX", "k": "品牌"}], [], []], "只有 e1 里真有 BrandX"
    sent.clear()
    rc, st = run(db, ask_ok, model="m", limit=10, batch_size=2, dry_run=False, max_seconds=60)
    assert rc == 0 and st["todo"] == 0 and sent == [], "列过、原文没变的不再送"
    db.tables["external_notes"][1]["body"] += " 后来买了 BrandX"
    rc, st = run(db, ask_ok, model="m", limit=10, batch_size=2, dry_run=False, max_seconds=60)
    assert rc == 0 and st["todo"] == 1 and sent == [1], "正文变了 (text_sha 对不上) → 重列这一篇"
    e2 = next(r for r in db.tables[X.MASK_TABLE] if r["note_id"] == "e2")
    assert e2["terms"] == [{"t": "BrandX", "k": "品牌"}] and e2["text_sha"] == X.mask_text_sha(
        db.tables["external_notes"][1]["title"], db.tables["external_notes"][1]["body"])
    db2 = _DB({"external_notes": [dict(n) for n in notes], X.MASK_TABLE: []})
    rc, st = run(db2, lambda p: "不是 JSON", model="m", limit=10, batch_size=2, dry_run=False, max_seconds=60)
    assert rc == 1 and st["junk"] == 3 and st["splits"] == 1 and db2.tables[X.MASK_TABLE] == [], \
        "垃圾回复: 先拆开重列, 拆到一篇还是垃圾才跳过、按篇计错、不写"
    # ③b review: 回到一半被 max_tokens 截断 (小模型默认带思考) → 拆批重列, 小批能回全就都写上、不算失败;
    #     一篇怎么都回不好 → 只丢那一篇, 同批别的照写 (以前整批每晚一起失败, 永远列不上)
    eight = [{"note_id": f"k{i}", "title": f"第{i}篇", "body": f"用了 BrandX 第{i}次", "fetched_at": "2026-11-03"}
             for i in range(8)]
    sizes: list = []

    def ask_cut(prompt):
        k = prompt.count("<note id=")
        sizes.append(k)
        full = ask_ok(prompt)
        return (full[: len(full) // 2], "max_tokens") if k > 2 else (full, "end_turn")
    db3 = _DB({"external_notes": [dict(n) for n in eight], X.MASK_TABLE: []})
    rc, st = run(db3, ask_cut, model="m", limit=10, batch_size=8, dry_run=False, max_seconds=60)
    assert rc == 0 and st["written"] == 8 and st["junk"] == 0 and st["splits"] == 3 and sizes == [8, 4, 2, 2, 4, 2, 2], \
        (rc, st, sizes)
    assert all(r["terms"] == [{"t": "BrandX", "k": "品牌"}] for r in db3.tables[X.MASK_TABLE])

    def ask_poison(prompt):
        return "{\"notes\": [" if "第5篇" in prompt else ask_ok(prompt)
    db4 = _DB({"external_notes": [dict(n) for n in eight], X.MASK_TABLE: []})
    rc, st = run(db4, ask_poison, model="m", limit=10, batch_size=8, dry_run=False, max_seconds=60)
    assert rc == 1 and st["junk"] == 1 and st["written"] == 7 and \
        sorted(r["note_id"] for r in db4.tables[X.MASK_TABLE]) == [f"k{i}" for i in range(8) if i != 5], st
    assert _reply(("x", "max_tokens")) == ("x", "max_tokens") and _reply("x") == ("x", None) and _reply(None) == ("", None)
    _selftest_stop_reason()
    # ④ 调用失败: 连着 3 批失败就停; 表没建 rc=2; 读不了外部表 rc=2; 写库失败 rc=1; dry-run 不写; limit / 时间到点
    many = [{"note_id": f"z{i:02d}", "title": "t", "body": "b", "fetched_at": "2026-11-03"} for i in range(20)]
    calls: list = []

    def boom(p):
        calls.append(1)
        raise RuntimeError("401 auth")
    rc, st = run(_DB({"external_notes": many, X.MASK_TABLE: []}), boom, model="m", limit=100, batch_size=2,
                 dry_run=False, max_seconds=60)
    assert rc == 1 and len(calls) == MAX_CONSECUTIVE_API_FAILS and st["left"] == 20 - 2 * MAX_CONSECUTIVE_API_FAILS, st
    missing = RuntimeError("{'code': 'PGRST205', 'message': \"Could not find the table 'truth_vault.external_note_masks'\"}")
    assert run(_DB({"external_notes": many, X.MASK_TABLE: missing}), ask_ok, model="m", limit=5, batch_size=2,
               dry_run=False, max_seconds=60)[0] == 2
    assert run(_DB({"external_notes": RuntimeError("down"), X.MASK_TABLE: []}), ask_ok, model="m", limit=5,
               batch_size=2, dry_run=False, max_seconds=60)[0] == 2
    rc, st = run(_DB({"external_notes": many, X.MASK_TABLE: []}, fail_writes=True), ask_ok, model="m", limit=4,
                 batch_size=2, dry_run=False, max_seconds=60)
    assert rc == 1 and st["write_errors"] == 2 and st["written"] == 0
    d = _DB({"external_notes": many, X.MASK_TABLE: []})
    rc, st = run(d, ask_ok, model="m", limit=5, batch_size=2, dry_run=True, max_seconds=60)
    assert rc == 0 and st["written"] == 5 and st["left"] == 15 and d.tables[X.MASK_TABLE] == [], "dry-run 不写; limit 之外留到下一晚"
    tick = iter(range(0, 10_000, 100))
    rc, st = run(_DB({"external_notes": many, X.MASK_TABLE: []}), ask_ok, model="m", limit=100, batch_size=2,
                 dry_run=False, max_seconds=150, clock=lambda: float(next(tick)))
    assert rc == 0 and 0 < st["written"] < 20 and st["written"] + st["left"] == 20, st
    # ⑤ 排序: 最近抓到的先列
    order = [n["note_id"] for n in pending([{"note_id": "a", "fetched_at": "2026-10-01"},
                                             {"note_id": "b", "fetched_at": "2026-11-01"}], {})]
    assert order == ["b", "a"]
    print("  ✓ selftest: 只留原文里逐字出现的词 / 去重 / k 兜底 / 短拉丁词按词边界; 漏篇不写; 垃圾回复跳过计错不崩; "
          "截断 / 垃圾回复先拆批重列、拆到一篇还不行只丢那一篇; call_claude 把 stop_reason 带出来; "
          "列过的不再送、正文变了重列; 连着 3 批调用失败就停; 表没建 / 外部表读不了 rc=2; 写库失败 rc=1; dry-run 不写; "
          "limit / 时间到点留到下一晚; 最近抓到的先列")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="外部帖品牌 / 产品名遮挡词 (D-140): 模型只列词, 代码核过逐字出现才存")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    ap.add_argument("--dry-run", action="store_true", help="照常调模型、不写库")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    model = os.environ.get("MASK_MODEL") or DEFAULT_MODEL
    rc = 2
    try:
        print(f"外部帖遮挡词 (D-140) · 模型 {model} · 每批 {args.batch} 篇 · 最多 {args.limit} 篇 · {args.max_minutes:.0f} 分钟"
              + (" · dry-run 不写库" if args.dry_run else ""))
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("  没有 ANTHROPIC_API_KEY, 这一晚不列")
        else:
            from _common import get_supabase_client
            from annotate_essence_pass import call_claude

            def ask(prompt: str) -> tuple[str, Optional[str]]:
                meta: dict = {}
                text = call_claude(prompt, model, cached_system=SYSTEM, max_tokens=MAX_TOKENS, meta=meta)
                return text, meta.get("stop_reason")
            rc, st = run(get_supabase_client(), ask, model=model, limit=args.limit, batch_size=max(args.batch, 1),
                         dry_run=args.dry_run, max_seconds=args.max_minutes * 60)
            if st["notes"]:
                print(f"  外部帖 {st['notes']} 篇 · 要列 {st['todo']} 篇 · 这一晚送了 {st['sent']} 篇 ({st['batches']} 批) · "
                      f"写了 {st['written']} 篇 (其中 {st['with_terms']} 篇有要遮的词, 共 {st['terms']} 个) · "
                      f"调用失败 {st['api_errors']} 批 · 拆批重列 {st['splits']} 次 · 拆到一篇还回的不是 JSON {st['junk']} 篇 · "
                      f"回里漏了 {st['missing']} 篇 · "
                      f"写库失败 {st['write_errors']} 批 · 留到下一晚 {st['left']} 篇")
            print(usage_line(model))
    except Exception as exc:  # noqa: BLE001 —— advisory: 不让夜跑崩, 但哨兵照打
        print(f"  ⚠️  出错: {type(exc).__name__}: {str(exc)[:200]}")
        rc = 1
    print(f"{SENTINEL} rc={rc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
