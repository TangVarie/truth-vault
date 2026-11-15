#!/usr/bin/env python3
"""读者评论入库 (十三件事第 2 件, D-155): 巡查工具写的「评论区快照」/「评论区明细」→ truth_vault.comments, 和运营贴的行分得开。

    cd scripts && python check_reader_comments.py

只读, 不碰库, 不联网; 夹具全是合成的 (没有真实昵称、评论、项目)。假 PostgREST 记下每一次读写, 真的驱动 main()。

守得住什么:
  §1 快照拆行: 序号 / 方括号标记 (命中、置顶、作者、N赞、IP 属地) / 昵称 都剥掉; 40 字截断 → is_truncated; 「还有 N 条未显示」
     和「暂无评论」不成行; 正文自己以 [表情] 开头不被当成标记; 蓝词标记还原成词; 认不出的文字回 None (不动已有行)。
  §2 明细 JSON: 平台 ID、发布时刻、作者 / 置顶 / 命中、父评论; 作者标记不可信 → 未知; 版本不对 / 不是 JSON → None。
  §3 观测时刻: 快照行只在「巡查状态」= 正常 时取「最近检查时间」; 明细行取 JSON 的 t; 格子在 _undeclared 里也读得到。
  §4 入库 (main + 假库): 第一次写入、重跑零写; 快照变了只换这一篇的快照行; 运营贴的行一行不动、巡查来的行不被报成
     「源里找不到了」; 一篇两格都有 → 只用明细、原来的快照行删掉; 明细行掉出第一页不删。
  §5 没跑 v1.27 的库 (没有 source 这一列): 运营那条路的写入和以前逐行一样, 巡查来的行一行不写, 只喊一次。
  §6 昵称和 IP 属地不落库; 命中关键词的行 is_scripted = true, 没命中的是空; 推给三省六部的样本评论和楼层重建不带巡查来的行。
反证 (改坏之后必须变红; 每条都真的试过):
  ① plan_linkcheck_rows 里去掉 status == STATUS_OK 那个条件 → §3 红
  ② parse_digest 不剥昵称 (去掉 _NICK_RE 那一步) → §1 / §6 红
  ③ fetch_project_comments_by_source 不按 source 分 (全进运营那一份) → §4 红 (重跑时每条都被当成新的再写一遍)
  ④ main 里没迁移也照走巡查那条路 (去掉 not lineage 的分支) → §5 红
  ⑤ plan 里 deletes 对明细行也按「不在这一页就删」算 → §4「掉出第一页不删」红
  ⑥ 两格都有时先用快照 → §4「只用明细」红
  ⑦ seed_needles 把列表一律当多选 (不拼分段再拆) → §1 红
  ⑧ plan 里去掉「已是贴主的不降成未知」→ §4 红
  ⑨ plan 里去掉「库里时刻是空的、这一轮拿得准就补」→ §3 红
挡不住什么:
  · 快照截到 40 字, 关键词落在 40 字之后的铺评认不出; 没填「评论关键词」的行分不出铺评。
  · 关了昵称落库的表, 正文里自带「xx: 」的开头会被当成昵称剥掉。
  · 真 PostgREST 的 upsert / delete 语义这里是假的; 三列的类型由 scripts/check_reader_comments_observations.sql 在真 Postgres 上守。
"""
from __future__ import annotations

import json
import logging
import os
import sys

import _common
import sync_comments_from_raw_extra as M

for _h in list(M.logger.handlers):      # 同步脚本自己的日志不往 CI 输出里刷; _drive 另挂一个 handler 收着断言用
    M.logger.removeHandler(_h)
M.logger.propagate = False

PROJ = "P_phase1"
T1, T2 = 1793606400000, 1793692800000          # 2026-11-02 08:00Z / 2026-11-03 08:00Z
ISO1, ISO2 = "2026-11-02T08:00:00+00:00", "2026-11-03T08:00:00+00:00"
NICKS = ("合成昵称甲", "合成昵称乙", "合成昵称丙", "合成昵称丁")
LONG39 = ("这是一条为了测试截断而写得特别长的合成评论" * 3)[:39]
assert len(LONG39) == 39

DIGEST_A = "\n".join([
    f"1. [命中「测试词」 · 置顶 · 3赞 · 广东] {NICKS[0]}: 用了测试词之后感觉还行",
    f"2. [作者 · 12赞] {NICKS[1]}: 谢谢大家的反馈",
    f"3. [浙江] {NICKS[2]}: {LONG39}…",
    f"4. {NICKS[3]}: 想问下是这个 #合成蓝词[搜索高亮]# 吗",
    f"5. {NICKS[3]}: [笑哭R] 这也太真实了",
    "…（还有 3 条未显示）",
])


class _Resp:
    def __init__(self, data):
        self.data = data


class _SB:
    """notes / comments 两张表的假 PostgREST。lineage=False 时, 读写里带 source 这一列就回「没有这一列」。"""

    def __init__(self, notes, comments, lineage=True):
        self.tables = {"notes": [dict(r) for r in notes], "comments": [dict(r) for r in comments]}
        self.lineage = lineage
        self.log: list[tuple] = []          # (op, table, detail)
        self._t = self._op = self._cols = self._payload = None
        self._f: list = []
        self._neg = False
        self._rng = None
        self._lim = None

    def schema(self, _):
        return self

    def table(self, name):
        self._t, self._op, self._cols, self._payload, self._f, self._neg, self._rng, self._lim = \
            name, None, "", None, [], False, None, None
        return self

    def select(self, cols="*", **k):
        self._op, self._cols = "select", cols
        return self

    def eq(self, k, v):
        self._f.append(("eq", k, v)); return self

    def in_(self, k, v):
        self._f.append(("in", k, list(v))); return self

    @property
    def not_(self):
        self._neg = True; return self

    def is_(self, k, v):
        self._f.append(("isnot" if self._neg else "is", k, v)); self._neg = False; return self

    def order(self, *a, **k):
        return self

    def range(self, a, b):
        self._rng = (a, b); return self

    def limit(self, n):
        self._lim = n; return self

    def insert(self, rows):
        self._op, self._payload = "insert", rows; return self

    def upsert(self, rows, on_conflict=None):
        assert on_conflict == "comment_id"
        self._op, self._payload = "upsert", rows; return self

    def update(self, patch):
        self._op, self._payload = "update", patch; return self

    def delete(self):
        self._op = "delete"; return self

    def _match(self, r):
        for kind, k, v in self._f:
            if kind == "eq" and r.get(k) != v:
                return False
            if kind == "in" and r.get(k) not in v:
                return False
            if kind == "isnot" and r.get(k) is None:
                return False
            if kind == "is" and r.get(k) is not None:
                return False
        return True

    def _no_such_column(self, names):
        if not self.lineage and self._t == "comments" and any(c in names for c in M.LINEAGE_COLS):
            raise RuntimeError("{'code': '42703', 'message': 'column comments.source does not exist'}")

    def execute(self):
        rows = self.tables[self._t]
        if self._op == "select":
            self._no_such_column(self._cols + " " + " ".join(k for _, k, _v in self._f))
            self.log.append(("select", self._t, tuple(self._f)))
            data = sorted((dict(r) for r in rows if self._match(r)),
                          key=lambda r: r.get("comment_id") or r.get("note_id") or "")
            if self._t == "comments" and self.lineage:
                for r in data:                       # 真 PostgREST: 选了的列一定有键, 没值是 null
                    for c in ("source", "is_truncated", "observed_at", "is_pinned", "is_scripted", "parent_comment_id"):
                        r.setdefault(c, None)
            if self._rng is not None:
                data = data[self._rng[0]:self._rng[1] + 1]
            if self._lim is not None:
                data = data[: self._lim]
            return _Resp(data)
        if self._op in ("insert", "upsert"):
            assert len({tuple(sorted(r)) for r in self._payload}) == 1, "一批里每行的键必须一样 (PostgREST 的要求)"
            self._no_such_column(" ".join(self._payload[0]))
            ids = {r["comment_id"]: r for r in rows}
            for r in self._payload:
                if self._op == "insert":
                    assert r["comment_id"] not in ids, f"主键冲突 {r['comment_id']}"
                if r.get("parent_comment_id"):
                    assert r["parent_comment_id"] in ids, f"外键: 父评论 {r['parent_comment_id']} 还不在库里"
                if r["comment_id"] in ids:
                    ids[r["comment_id"]].update(r)
                else:
                    rows.append(dict(r)); ids[r["comment_id"]] = rows[-1]
            self.log.append((self._op, self._t, [dict(r) for r in self._payload]))
            return _Resp(self._payload)
        if self._op == "update":
            for r in rows:
                if self._match(r):
                    r.update(self._payload)
            self.log.append(("update", self._t, dict(self._payload)))
            return _Resp([])
        if self._op == "delete":
            gone = [r["comment_id"] for r in rows if self._match(r)]
            assert all(k == "comment_id" for _, k, _v in self._f) and self._f, "删只许按 comment_id 点名"
            rows[:] = [r for r in rows if not self._match(r)]
            self.log.append(("delete", self._t, gone))
            return _Resp([])
        raise AssertionError(self._op)

    # —— 方便断言 ——
    def writes(self, op=None):
        return [x for x in self.log if x[0] != "select" and (op is None or x[0] == op)]

    def comment_ids(self, note_id=None, source="any"):
        return sorted(r["comment_id"] for r in self.tables["comments"]
                      if (note_id is None or r["note_id"] == note_id)
                      and (source == "any" or r.get("source") == source))


def _note(nid, **raw):
    return {"note_id": nid, "project_id": PROJ, "raw_extra": raw}


def _op_row(nid, i, content, role="素人"):
    return {"comment_id": f"{nid}_h{i}", "note_id": nid, "project_id": PROJ, "content": content,
            "comment_role": role, "comment_order": i}


def _records(t, items, **outer):
    base = {"v": 1, "t": t, "n": len(items), "hid": 0, "kw": 1, "ar": 1, "pr": 1, "lim": 200, "more": 0}
    base.update(outer)
    base["c"] = [{"id": "", "ts": None, "a": 0, "p": 0, "l": 0, "k": 0, "r": "", "x": "", "tr": 0, **it} for it in items]
    return json.dumps(base, ensure_ascii=False, separators=(",", ":"))


def _drive(sb, argv=()):
    """真的跑 main(); 回 (rc, stats, 日志行)。"""
    saved = (M.get_supabase_client, M.fetch_all_pages, M.load_mapping)
    msgs: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            msgs.append(record.getMessage())
    h = _H()
    M.logger.addHandler(h)
    old_argv, old_env = sys.argv, os.environ.pop("TV_SCHEDULED_RUN", None)
    _common._MISSING_DB_OBJECT_WARNED.discard("comments.source")
    M._LINEAGE_SUPPORTED[:] = []
    try:
        M.get_supabase_client = lambda *a, **k: sb
        M.fetch_all_pages = lambda q, page_size=1000, order_by=None: list(q.execute().data)
        M.load_mapping = lambda pid: {"project_id": pid, "sync_config": {"sync_interval": "daily"}}
        sys.argv = ["x", PROJ, *argv]
        rc = M.main()
    finally:
        M.get_supabase_client, M.fetch_all_pages, M.load_mapping = saved
        M.logger.removeHandler(h)
        sys.argv = old_argv
        if old_env is not None:
            os.environ["TV_SCHEDULED_RUN"] = old_env
    done = [m for m in msgs if m.startswith("Done: ")]
    return rc, (json.loads(done[-1][len("Done: "):]) if done else None), msgs


# ── §1 快照拆行 ─────────────────────────────────────────────────────────────────
def check_parse_digest() -> None:
    rows = M.parse_digest(DIGEST_A, M.seed_needles("测试词、别的词"))
    got = [(r["role"], r["content"], r["is_pinned"], r["is_truncated"], r["seeded"], r["likes"]) for r in rows]
    want = [
        ("路人", "用了测试词之后感觉还行", True, False, True, 3),
        ("贴主", "谢谢大家的反馈", False, False, False, 12),
        ("路人", LONG39 + "…", False, True, False, None),
        ("路人", "想问下是这个 合成蓝词 吗", False, False, False, None),
        ("路人", "[笑哭R] 这也太真实了", False, False, False, None),
    ]
    assert got == want, f"§1 快照拆出来的不对:\n{got}"
    # 没带「命中」标记、但正文里有关键词的那条也算命中 (linkcheck 只给第一条命中的打标记)
    two = M.parse_digest("1. [命中「测试词」] 甲: 测试词不错\n2. 乙: 我也觉得 测试 词 可以", M.seed_needles(["测试词"]))
    assert [r["seeded"] for r in two] == [True, True], "§1 正文里出现关键词 (宽松匹配) 的也要标命中"
    # 「评论关键词」是文本列时, 飞书给的是富文本分段 [{text, type}]: 要和纯字符串一样拆开 (同 linkcheck read_keywords),
    # 不然整格并成一个词, 没带「命中」标记的铺评一条都认不出
    seg = [{"text": "词甲、词乙", "type": "text"}]
    assert M.seed_needles(seg) == ["词甲", "词乙"] == M.seed_needles("词甲、词乙"), f"§1 分段的关键词格没拆开: {M.seed_needles(seg)}"
    assert M.seed_needles([{"text": "词甲、", "type": "text"}, {"text": "词乙", "type": "text"}]) == ["词甲", "词乙"]
    assert M.seed_needles([{"name": "词甲", "id": "opt1"}, "词乙"]) == ["词甲", "词乙"], "§1 多选的选项对象要取 name"
    assert M.seed_needles(["词甲、词乙"]) == ["词甲词乙"], "§1 多选的一个选项是一个词, 不再拆 (同 linkcheck)"
    assert M.seed_needles(None) == [] and M.seed_needles([]) == [] and M.seed_needles(["带 空格的词"]) == ["带空格的词"]
    segd = M.parse_digest("1. [命中「词甲」] 甲: 词甲不错\n2. 乙: 词乙也好\n3. 丙: 都没提到", M.seed_needles(seg))
    assert [r["seeded"] for r in segd] == [True, True, False], f"§1 分段的关键词格: 第二个词的铺评没认出来 {segd}"
    # 关了昵称落库的表: 正文以 [表情] 开头, 不能被当成标记段吃掉
    assert [r["content"] for r in M.parse_digest("1. [笑哭R] 哈哈哈")] == ["[笑哭R] 哈哈哈"], "§1 [表情] 开头被当成了标记"
    assert M.parse_digest("（暂无评论）") == [] and M.parse_digest("（接口报评论数 7，但评论区一条都看不到：被删除）") == [], \
        "§1 占位行 = 认得、没有评论"
    assert M.parse_digest("运营随手写的一句话") is None and M.parse_digest("") is None, "§1 认不出的文字要回 None"
    assert M.parse_digest("1. 甲: \n2. 乙:") == [], "§1 昵称后面是空的 (纯图片评论) 不成行, 也不能把昵称当正文"
    # 39 字 + 「…」才是截断; 自己以「…」结尾的短评论不是
    assert [r["is_truncated"] for r in M.parse_digest("1. 甲: 嗯…")] == [False], "§1 短评论自己带的省略号不是截断"
    print("  §1 快照: 标记 / 昵称 / IP 剥掉, 截断、置顶、作者、命中认得出, 占位和认不出的分得开 ✓")


# ── §2 明细 JSON ─────────────────────────────────────────────────────────────────
def check_parse_records() -> None:
    text = _records(T1, [
        {"id": "aa01", "ts": T1 - 3600000, "a": 0, "p": 1, "l": 5, "k": 1, "x": "合成的置顶评论 #合成蓝词[搜索高亮]#"},
        {"id": "aa02", "a": 1, "x": "合成的作者回复"},
        {"id": "aa01", "x": "同一个 ID 又来一次"},
        {"id": "", "x": "上游没给 ID 的一条", "tr": 1},
        {"id": "bb01", "r": "aa01", "x": "楼中楼回复"},
        {"id": "cc01", "x": "   "},
    ])
    p = M.parse_records(text)
    assert p["observed_at"] == ISO1, p["observed_at"]
    got = [(r["upstream_id"], r["role"], r["content"], r["is_pinned"], r["is_truncated"], r["seeded"],
            r["parent_upstream_id"], r["comment_time"]) for r in p["rows"]]
    want = [
        ("aa01", "路人", "合成的置顶评论 合成蓝词", True, False, True, "", "2026-11-02T07:00:00"),
        ("aa02", "贴主", "合成的作者回复", False, False, False, "", None),
        ("", "路人", "上游没给 ID 的一条", False, True, False, "", None),
        ("bb01", "路人", "楼中楼回复", False, False, False, "aa01", None),
    ]
    assert got == want, f"§2 明细读出来的不对:\n{got}"
    unsure = M.parse_records(_records(T1, [{"id": "aa01", "x": "谁发的不知道"}], ar=0))
    assert [r["role"] for r in unsure["rows"]] == ["未知"], "§2 作者标记这一轮不可信 → 未知, 不能写成路人"
    assert M.parse_records("{坏的") is None and M.parse_records(_records(T1, [], v=2)) is None \
        and M.parse_records('{"v":1,"c":"x"}') is None, "§2 认不出的明细要回 None"
    assert M.parse_records(_records(None, []))["observed_at"] is None, "§2 t 不是时间戳 → 观测时刻空, 不代填"
    print("  §2 明细: 平台 ID / 发布时刻 / 父评论 / 命中 / 截断读得出, 重复 ID 留第一次, 认不出回 None ✓")


# ── §3 观测时刻 ─────────────────────────────────────────────────────────────────
def check_observed_at() -> None:
    def obs(**raw):
        plan = M.plan_linkcheck_rows(_note("n1", **raw), [])
        return plan["source"], sorted({r["observed_at"] for r in plan["upserts"]}, key=str)
    one = "1. 甲: 合成评论一"
    assert obs(评论区快照=one, 最近检查时间=T1, 巡查状态="正常") == (M.SOURCE_DIGEST, [ISO1])
    assert obs(评论区快照=one, 最近检查时间=T2, 巡查状态="刷新失败") == (M.SOURCE_DIGEST, [None]), \
        "§3 巡查失败的轮次也推进「最近检查时间」: 这时不能拿它当快照的观测时刻"
    assert obs(评论区快照=one, 最近检查时间=T2) == (M.SOURCE_DIGEST, [None]), "§3 没有巡查状态 → 不填"
    assert obs(评论区快照=one, 最近检查时间="不是数", 巡查状态="正常") == (M.SOURCE_DIGEST, [None])
    # mapping 没声明的列在 _undeclared 里; 飞书文本格可能是分段
    assert obs(_undeclared={"评论区快照": [{"text": one, "type": "text"}], "最近检查时间": T1, "巡查状态": "正常"}) \
        == (M.SOURCE_DIGEST, [ISO1]), "§3 _undeclared 里的格子也要读得到"
    # 明细: 用 JSON 里的 t, 不看巡查状态 (那一格只在真看到评论页时才写)
    assert obs(评论区明细=_records(T1, [{"id": "aa01", "x": "合成评论一"}]), 最近检查时间=T2, 巡查状态="刷新失败") \
        == (M.SOURCE_RECORDS, [ISO1]), "§3 明细行的观测时刻 = JSON 的 t"
    # 已有的行这一轮只是位置变了、而这一轮拿不准时刻: 不拿空值盖掉以前记下的
    first = M.plan_linkcheck_rows(_note("n1", 评论区快照=one + "\n2. 乙: 合成评论二", 最近检查时间=T1, 巡查状态="正常"), [])
    stored = [dict(r) for r in first["upserts"]]
    again = M.plan_linkcheck_rows(
        _note("n1", 评论区快照="1. 乙: 合成评论二\n2. 甲: 合成评论一", 最近检查时间=T2, 巡查状态="疑似受限"), stored)
    assert len(again["upserts"]) == 2 and {r["observed_at"] for r in again["upserts"]} == {ISO1} and not again["deletes"], \
        f"§3 位置变了重写时把以前的观测时刻冲成空了: {again}"
    # 第一次入库赶上巡查没成功 (时刻空), 下一轮巡查正常、快照一个字没变: 要把时刻补上 —— 以前这种行永远是空的
    two = one + "\n2. 乙: 合成评论二"
    for bad in ("刷新失败", "跳过", "冷却跳过", "留待下一轮"):
        night1 = M.plan_linkcheck_rows(_note("n1", 评论区快照=two, 最近检查时间=T1, 巡查状态=bad), [])
        held = [dict(r) for r in night1["upserts"]]
        assert len(held) == 2 and {r["observed_at"] for r in held} == {None}, f"§3 {bad} 那一轮不该有时刻"
        night2 = M.plan_linkcheck_rows(_note("n1", 评论区快照=two, 最近检查时间=T2, 巡查状态="正常"), held)
        assert [r["observed_at"] for r in night2["upserts"]] == [ISO2, ISO2] and not night2["deletes"] \
            and [r["comment_id"] for r in night2["upserts"]] == [r["comment_id"] for r in held], \
            f"§3 {bad} 之后巡查正常了, 没变的行要补上观测时刻: {night2}"
    filled = [dict(r) for r in night2["upserts"]]
    night3 = M.plan_linkcheck_rows(_note("n1", 评论区快照=two, 最近检查时间=T2 + 86400000, 巡查状态="正常"), filled)
    assert not night3["upserts"] and not night3["deletes"], f"§3 时刻补过一次之后, 没变的行不再重写: {night3}"
    # 没有平台 ID 的明细行: 第一轮认出是作者发的, 第二轮作者标记不可信 (ar=0) —— 还是那一行, 不多出一份「未知」
    r1 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T1, [{"x": "合成作者回复", "a": 1}])), [])
    kept = [dict(r) for r in r1["upserts"]]
    assert len(kept) == 1 and kept[0]["comment_role"] == "贴主"
    r2 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T2, [{"x": "合成作者回复", "a": 0}], ar=0)), kept)
    assert not r2["upserts"] and not r2["deletes"], f"§3 作者标记不可信的那一轮把作者回复另存成了一行未知: {r2}"
    # 有平台 ID 的行: 这一轮没带发表时间、又有别的字段变了要重写 —— 以前记下的发表时间留着
    r1 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T1, [{"id": "a" * 24, "x": "合成读者评论", "ts": T1}])), [])
    kept = [dict(r) for r in r1["upserts"]]
    assert kept[0]["comment_time"] and kept[0]["comment_role"] == "路人"
    r2 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T2, [{"id": "a" * 24, "x": "合成读者评论"}], ar=0)), kept)
    assert len(r2["upserts"]) == 1 and r2["upserts"][0]["comment_role"] == "未知" \
        and r2["upserts"][0]["comment_time"] == kept[0]["comment_time"], f"§3 重写时把发表时间冲成空了: {r2}"
    # 同一条评论后来被置顶了 (别的字段变了要重写): 第一次读到它的时刻不往后挪
    r1 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T1, [{"id": "b" * 24, "x": "合成读者评论"}])), [])
    kept = [dict(r) for r in r1["upserts"]]
    r2 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T2, [{"id": "b" * 24, "x": "合成读者评论", "p": 1}])), kept)
    assert len(r2["upserts"]) == 1 and r2["upserts"][0]["is_pinned"] and r2["upserts"][0]["observed_at"] == ISO1, \
        f"§3 别的字段变了重写时把第一次观测的时刻挪后了: {r2}"
    # 第一次入库没带发表时间, 后来带了、别的一个字没变: 要补上; 补过之后 (库里读回来写法不同也算同一刻) 不再重写
    r3 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T2, [{"id": "b" * 24, "x": "合成读者评论", "ts": T1}])), kept)
    assert len(r3["upserts"]) == 1 and r3["upserts"][0]["comment_time"], f"§3 后来才拿到的发表时间没补上: {r3}"
    back = [dict(r3["upserts"][0], comment_time=r3["upserts"][0]["comment_time"] + ".000000")]
    r4 = M.plan_linkcheck_rows(_note("n1", 评论区明细=_records(T2, [{"id": "b" * 24, "x": "合成读者评论", "ts": T1}])), back)
    assert not r4["upserts"], f"§3 发表时间补过之后不该每晚重写: {r4}"
    print("  §3 观测时刻: 快照行只在巡查正常时取最近检查时间; 明细行取 t; _undeclared 也读; 重写不冲掉旧时刻; 失败轮入库的行之后补一次 ✓")


# ── §4 入库 ─────────────────────────────────────────────────────────────────────
def check_sync() -> None:
    notes = [
        _note("n1", _comment_text="1. 运营贴的一\n2. 运营贴的二", 评论区快照=DIGEST_A, 评论关键词="测试词", 最近检查时间=T1, 巡查状态="正常"),
        _note("n2", 评论区快照="1. 甲: 另一篇的读者评论\n2. 乙: 另一篇的读者评论", 最近检查时间=T1, 巡查状态="正常"),
        _note("n3", _comment_text="1. 只有运营贴的"),
    ]
    sb = _SB(notes, [_op_row("n1", 1, "运营贴的一"), _op_row("n1", 2, "运营贴的二"), _op_row("n3", 1, "只有运营贴的")])
    rc, st, msgs = _drive(sb)
    assert rc == 0 and st["reader_notes"] == 2 and st["reader_rows_written"] == 7 and st["reader_rows_deleted"] == 0, st
    assert st["comments_written"] == 0 and st["vanished_other"] == 0 and st["notes_source_cleared"] == 0, \
        f"§4 运营那条路不该受影响: {st}"
    lc1 = sb.comment_ids("n1", M.SOURCE_DIGEST)
    assert len(lc1) == 5 and all(c.startswith("n1_lcd") for c in lc1), lc1
    n2 = sb.comment_ids("n2", M.SOURCE_DIGEST)
    assert len(n2) == 2 and n2[0][:-1] == n2[1][:-1] and {n2[0][-2:], n2[1][-2:]} == {"_1", "_2"}, \
        f"§4 同一页里一模一样的两条要各有各的 id: {n2}"
    rows = {r["comment_id"]: r for r in sb.tables["comments"]}
    hit = next(r for r in rows.values() if r["content"] == "用了测试词之后感觉还行")
    assert hit["is_scripted"] is True and hit["is_pinned"] is True and hit["observed_at"] == ISO1 \
        and hit["raw_extra"] == {"likes": 3}, hit
    plain = next(r for r in rows.values() if r["content"] == "[笑哭R] 这也太真实了")
    assert plain["is_scripted"] is None and plain["comment_role"] == "路人" and plain["is_truncated"] is False, plain
    assert sum(1 for r in rows.values() if r.get("is_truncated")) == 1
    assert all(rows[c].get("source") is None for c in ("n1_h1", "n1_h2", "n3_h1")), "§4 运营贴的行 source 要一直是空"
    assert len(sb.writes()) == 1 and sb.writes()[0][0] == "upsert", f"§4 整个项目攒成一批写: {sb.writes()}"

    # 重跑: 零写
    before = json.dumps(sb.tables["comments"], ensure_ascii=False, sort_keys=True)
    sb.log.clear()
    rc, st, _ = _drive(sb)
    assert rc == 0 and not sb.writes() and st["reader_rows_written"] == 0 and st["comments_written"] == 0, \
        f"§4 重跑不该有任何写: {sb.writes()}"
    assert json.dumps(sb.tables["comments"], ensure_ascii=False, sort_keys=True) == before
    assert st["vanished_other"] == 0 and st["vanished_parser_change"] == 0 and st["notes_source_cleared"] == 0, \
        f"§4 巡查来的行不该被报成找不到了 (n2 没有运营评论, 也不该算「源被清空」): {st}"

    # n1 的快照变了 (第 2 条没了, 多了一条新的; 这一轮巡查失败): 只换 n1 的快照行
    sb.tables["notes"][0]["raw_extra"]["评论区快照"] = "\n".join(
        [l for l in DIGEST_A.splitlines() if not l.startswith("2. ")] + ["6. 戊: 新冒出来的一条"])
    sb.tables["notes"][0]["raw_extra"].update(最近检查时间=T2, 巡查状态="刷新失败")
    sb.log.clear()
    rc, st, _ = _drive(sb)
    assert rc == 0 and st["reader_rows_deleted"] == 1, st
    gone = [x for x in sb.writes("delete")]
    assert len(gone) == 1 and len(gone[0][2]) == 1 and gone[0][2][0] in lc1, gone
    now1 = sb.comment_ids("n1", M.SOURCE_DIGEST)
    assert len(now1) == 5 and len(set(now1) & set(lc1)) == 4, "§4 没变的四条 id 不变, 一条删、一条新"
    new = next(r for r in sb.tables["comments"] if r["content"] == "新冒出来的一条")
    assert new["observed_at"] is None, "§4 巡查失败那一轮新出现的行不填观测时刻"
    assert sb.comment_ids("n2", M.SOURCE_DIGEST) == n2 and sb.comment_ids(None, None) == ["n1_h1", "n1_h2", "n3_h1"], \
        "§4 别的篇和运营贴的行一行不动"
    assert all(x[1] == "comments" and (x[0] != "upsert" or all(r["note_id"] == "n1" for r in x[2])) for x in sb.writes())

    # 快照被写成认不出的东西: 已有的行不动, 说一声
    sb.tables["notes"][1]["raw_extra"]["评论区快照"] = "有人手改了这一格"
    sb.log.clear()
    rc, st, msgs = _drive(sb)
    assert rc == 0 and not sb.writes() and st["reader_unreadable"] == 1 and sb.comment_ids("n2", M.SOURCE_DIGEST) == n2, \
        f"§4 认不出的快照不该删已有的行: {sb.writes()}"
    assert any("认不出" in m for m in msgs)
    # 快照变成「暂无评论」: 这一篇的快照行清掉
    sb.tables["notes"][1]["raw_extra"]["评论区快照"] = "（暂无评论）"
    rc, st, _ = _drive(sb)
    assert rc == 0 and sb.comment_ids("n2", M.SOURCE_DIGEST) == [] and st["reader_rows_deleted"] == 2

    # n1 有了明细: 只用明细, 快照行整套删掉; 明细行 id 用平台 ID, 楼中楼挂到父评论上
    sb.tables["notes"][0]["raw_extra"]["评论区明细"] = _records(T2, [
        {"id": "aa01", "p": 1, "k": 1, "l": 3, "x": "用了测试词之后感觉还行"},
        {"id": "aa02", "a": 1, "x": "谢谢大家的反馈"},
        {"id": "bb01", "r": "aa01", "x": "楼中楼回复"},
        {"id": "bb02", "r": "zz99", "x": "父评论不在这一页的回复"},
    ])
    sb.log.clear()
    rc, st, _ = _drive(sb)
    assert rc == 0 and sb.comment_ids("n1", M.SOURCE_DIGEST) == [], "§4 两格都有时只用明细: 快照行要删掉"
    rec = sb.comment_ids("n1", M.SOURCE_RECORDS)
    assert rec == ["n1_lcraa01", "n1_lcraa02", "n1_lcrbb01", "n1_lcrbb02"], rec
    rows = {r["comment_id"]: r for r in sb.tables["comments"]}
    assert rows["n1_lcrbb01"]["parent_comment_id"] == "n1_lcraa01" and rows["n1_lcrbb02"]["parent_comment_id"] is None
    assert rows["n1_lcraa01"]["observed_at"] == ISO2 and rows["n1_lcraa01"]["is_scripted"] is True \
        and rows["n1_lcraa02"]["comment_role"] == "贴主"
    assert [x[0] for x in sb.writes()] == ["delete", "upsert"], "§4 先删后写"

    # 下一轮第一页换了人: 掉出去的明细行不删; 同一条置顶没了 → 更新那一行; 没变的不重写
    sb.tables["notes"][0]["raw_extra"]["评论区明细"] = _records(T2 + 1000, [
        {"id": "aa01", "p": 0, "k": 1, "l": 9, "x": "用了测试词之后感觉还行"},
        {"id": "dd01", "x": "新排上来的一条"},
    ])
    sb.log.clear()
    rc, st, _ = _drive(sb)
    assert rc == 0 and not sb.writes("delete"), "§4 明细行掉出第一页不删"
    assert sb.comment_ids("n1", M.SOURCE_RECORDS) == rec + ["n1_lcrdd01"]
    up = [r["comment_id"] for x in sb.writes("upsert") for r in x[2]]
    assert up == ["n1_lcraa01", "n1_lcrdd01"], f"§4 只写变了的和新的 (赞数变了不算变): {up}"
    # 作者标记这一轮不可信 (备用通道, ar = 0): 以前记成贴主的那条不降成未知 (降了就过了「不是贴主」的筛, 被数成读者评论),
    # 也不因此重写; 没见过的新行照旧是未知; 下一轮可信了, 未知的那条改成路人
    sb.tables["notes"][0]["raw_extra"]["评论区明细"] = _records(T2 + 2000, [
        {"id": "aa02", "a": 0, "x": "谢谢大家的反馈"},
        {"id": "ee01", "a": 0, "x": "这一轮才看到的一条"},
    ], ar=0)
    sb.log.clear()
    rc, st, _ = _drive(sb)
    rows = {r["comment_id"]: r for r in sb.tables["comments"]}
    assert rc == 0 and rows["n1_lcraa02"]["comment_role"] == "贴主", "§4 作者标记不可信的一轮把贴主降成了未知"
    assert rows["n1_lcree01"]["comment_role"] == "未知"
    assert [r["comment_id"] for x in sb.writes("upsert") for r in x[2]] == ["n1_lcree01"], \
        f"§4 作者标记不可信的一轮不该重写已有的贴主行: {sb.writes()}"
    sb.tables["notes"][0]["raw_extra"]["评论区明细"] = _records(T2 + 3000, [
        {"id": "aa02", "a": 1, "x": "谢谢大家的反馈"},
        {"id": "ee01", "a": 0, "x": "这一轮才看到的一条"},
    ])
    sb.log.clear()
    rc, st, _ = _drive(sb)
    rows = {r["comment_id"]: r for r in sb.tables["comments"]}
    assert rc == 0 and rows["n1_lcraa02"]["comment_role"] == "贴主" and rows["n1_lcree01"]["comment_role"] == "路人" \
        and [r["comment_id"] for x in sb.writes("upsert") for r in x[2]] == ["n1_lcree01"], sb.writes()
    rec = rec + ["n1_lcree01"]
    # 明细那一格后来空了: 不往上叠快照行
    sb.tables["notes"][0]["raw_extra"]["评论区明细"] = ""
    sb.log.clear()
    rc, st, _ = _drive(sb)
    assert rc == 0 and not sb.writes() and sb.comment_ids("n1", M.SOURCE_DIGEST) == [], "§4 已有明细行的篇不再叠快照行"

    # 运营把 n1 的随贴评论整个清空: 对账名单里只有运营贴的那两行, 没有巡查来的
    sb.tables["notes"][0]["raw_extra"]["_comment_text"] = ""
    out = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", "check_reader_comments_vanished.jsonl")
    rc, st, _ = _drive(sb, argv=("--dry-run", "--vanished-out", out))
    names = sorted(json.loads(l)["comment_id"] for l in open(out, encoding="utf-8"))
    os.remove(out)
    assert rc == 0 and names == ["n1_h1", "n1_h2"] and st["notes_source_cleared"] == 1, \
        f"§4 「源被清空」名单里混进了巡查来的行: {names}"
    print("  §4 入库: 首次写入 / 重跑零写 / 快照变了只换这一篇 / 认不出不删 / 两格都有只用明细 / 掉出第一页不删 / 对账不混 ✓")


# ── §5 没跑 v1.27 的库 ──────────────────────────────────────────────────────────
def check_unmigrated() -> None:
    def notes(with_lc):
        lc = dict(评论区快照=DIGEST_A, 评论区明细=_records(T1, [{"id": "aa01", "x": "合成评论"}]),
                  最近检查时间=T1, 巡查状态="正常") if with_lc else {}
        return [_note("n1", _comment_text="1. 新来的\n2. 好用\n3. 真的吗", **lc), _note("n2", _comment_text="1. 一般")]
    existing = [_op_row("n1", 1, "好用"), _op_row("n1", 2, "真的吗")]

    ref = _SB(notes(False), existing, lineage=False)
    rc0, st0, _ = _drive(ref)
    sb = _SB(notes(True), existing, lineage=False)
    rc, st, msgs = _drive(sb)
    assert rc == 0 == rc0 and st["reader_rows_written"] == 0 and st["reader_notes"] == 0, st
    assert not sb.writes("upsert") and not sb.writes("delete"), "§5 没有 source 这一列的库不该写巡查来的行"
    a = [(op, [{k: v for k, v in r.items() if k != "created_at"} for r in d] if op == "insert" else d)
         for op, _t, d in sb.writes()]
    b = [(op, [{k: v for k, v in r.items() if k != "created_at"} for r in d] if op == "insert" else d)
         for op, _t, d in ref.writes()]
    assert a == b and a, f"§5 运营那条路的写入要和以前逐行一样:\n{a}\n{b}"
    assert {k: v for k, v in st.items() if not k.startswith("reader_")} == \
           {k: v for k, v in st0.items() if not k.startswith("reader_")}
    assert all("source" not in r for _op, _t, d in sb.writes("insert") for r in d), "§5 运营行不写 source 这一列"
    warned = [m for m in msgs if "notes_v1_27" in m]
    assert len(warned) == 1, f"§5 要喊一次去跑哪份 SQL: {warned}"
    # 没有巡查格子的项目: 不喊
    _c, _s, msgs0 = _drive(_SB(notes(False), existing, lineage=False))
    assert not [m for m in msgs0 if "notes_v1_27" in m], "§5 项目里没有快照 / 明细就不用喊"
    # 别的错不能当成「没迁移」吞掉
    class _Down(_SB):
        def execute(self):
            if self._op == "select" and self._t == "comments":
                raise RuntimeError("connection reset")
            return super().execute()
    try:
        _drive(_Down(notes(True), existing))
    except RuntimeError as e:
        assert "connection reset" in str(e)
    else:
        raise AssertionError("§5 连不上要照抛, 不能当成没迁移悄悄降级")
    print("  §5 没跑 v1.27: 运营那条路逐行不变, 巡查来的行不写, 只喊一次; 连不上照抛 ✓")


# ── §6 昵称不落库 / 下游不带巡查来的行 ───────────────────────────────────────────
def check_privacy_and_consumers() -> None:
    sb = _SB([_note("n1", 评论区快照=DIGEST_A, 评论关键词=["测试词"], 最近检查时间=T1, 巡查状态="正常")], [])
    rc, st, _ = _drive(sb)
    blob = json.dumps(sb.tables["comments"], ensure_ascii=False)
    assert rc == 0 and st["reader_rows_written"] == 5
    for word in (*NICKS, "广东", "浙江", "搜索高亮"):
        assert word not in blob, f"§6 「{word}」落库了 (昵称 / IP 属地 / 标记不该进 comments)"
    scripted = [r["content"] for r in sb.tables["comments"] if r["is_scripted"]]
    assert scripted == ["用了测试词之后感觉还行"] and all(
        r["is_scripted"] in (True, None) for r in sb.tables["comments"]), "§6 命中 → true, 没命中 → 空 (不写 false)"

    # 推给三省六部的样本评论: 只取运营贴的
    import sync_truth_vault_baokuan_to_sanshengliubu as S
    sb.tables["comments"].append({**_op_row("n1", 1, "运营贴的一"), "is_pinned": False})
    S._COMMENT_SOURCE_COL[:] = []
    got = [c["content"] for c in S.fetch_top_comments(sb, "n1", limit=5)]
    assert got == ["运营贴的一"], f"§6 样本评论里混进了读者评论: {got}"
    old = _SB([], [{**_op_row("n1", 1, "运营贴的一"), "is_pinned": False}], lineage=False)
    S._COMMENT_SOURCE_COL[:] = []
    assert [c["content"] for c in S.fetch_top_comments(old, "n1")] == ["运营贴的一"] and S._COMMENT_SOURCE_COL == [False], \
        "§6 没有 source 这一列的库: 照原样取"
    n_sel = len(old.log)
    S.fetch_top_comments(old, "n1")
    assert len(old.log) == n_sel + 1, "§6 「没有这一列」只探一次, 之后每篇一次读"
    S._COMMENT_SOURCE_COL[:] = []
    assert M.is_linkcheck_comment_id("n1_lcd0123456789ab_1", "n1") and M.is_linkcheck_comment_id("n1_lcraa01", "n1") \
        and not M.is_linkcheck_comment_id("n1_h0123456789ab_1", "n1") and not M.is_linkcheck_comment_id("n1_c3", "n1")
    print("  §6 昵称 / IP 属地不落库; 命中标 is_scripted; 样本评论只取运营贴的, 没迁移照原样 ✓")


def main() -> int:
    check_parse_digest()
    check_parse_records()
    check_observed_at()
    check_sync()
    check_unmigrated()
    check_privacy_and_consumers()
    print("\ncheck_reader_comments: 6 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
