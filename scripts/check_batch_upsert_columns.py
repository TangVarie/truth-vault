#!/usr/bin/env python3
"""批量 upsert 不许把「没带的列」冲成 NULL (2026-10-20 事故, D-122)。

事故: upsert_notes_batch 一次 upsert 500 行。postgrest-py 2.30.0 把 columns= 设成这一批所有行的键的
并集, 没带的键补 NULL, 加上 resolution=merge-duplicates 就是 ON CONFLICT DO UPDATE SET col = NULL。
transform_row 只给方向能直接抬的行写 content_format 等四列, 抬不了的行这四列归 essence ——
于是每晚同批里抬得了的行把抬不了的行的 essence 值冲掉。10-20 生产 744 篇 content_format 没了。

断行为不断源码 (D-051): 不打桩 upsert_notes_batch 自己, 打桩的是最底下的 HTTP —— 用真的 postgrest-py
request builder 发请求, httpx.MockTransport 收下来, 按 PostgREST 真看到的东西(URL 里的 columns=、
请求体里每一行带了哪些键)判。行由真 mapping + 真 transform_row + main 里那几道闸生成。

不变式: 每一个带 columns= 的请求里, 对 UPSERT_PROTECTED_COLS 里出现在 columns= 的每一列, 这个请求的
每一行都带着这个键(值是 None 也算带 —— 那是故意清档)。

  §1 每张真 mapping 的混方向批 (抬得了 / 有子方向 / 方向没映上 / 没填方向 混在一批) —— 不变式 + 每篇正好写一次
  §2 整批 tier 翻转被挡 (apply_tier_flip_block 剥掉 tier/tier_source) —— 被挡的篇只进不带 tier 的请求
  §3 状态列整轮消失 (核心列消失那条路, 只有数值推断的篇带 tier) —— 不带 tier 的篇只进不带 tier 的请求;
     同一条路上只有少数篇判出旗子时, 没旗子的篇只进不带 data_quality_flags 的请求
  §4 镜像口径没被顺手改掉: 不按完整键集分组, 指标格子没带的行照旧和带的行同批 (= 写成 NULL)
  §5 名单本身: 都是真列; 飞书格子不许直接映进名单里的列; essence / 写作台会写、本脚本也写的列都在名单里
  §6 反证: 老写法 (一把 upsert 整批) 在 §1 的批上必须被判红; 名单清空后 upsert_notes_batch 必须被判红
  §7 逐行兜底照旧: 批请求被拒 → 逐行写 (单行不带 columns=), 返回值 / 失败篇的处理不变; dry-run 不发请求
  §8 名单逐列: 有证据的 11 列一列都不许少 (要删先写 D 号再改这里); 每一列带 (哪怕是 None) / 不带都分开

反证 (改坏之后必须变红; D-122 记了实跑结果):
  ① 换回老实现 (整批按 500 一切)               → §1 / §2 / §3 红
  ② 按完整键集分组                              → §4 红 (镜像飞书的口径被顺手改掉)
  ③ 名单里删掉任一列 (11 列逐列试过)            → 删 essence 共写的四列 / lineage 两列 → §5 红;
                                                  删 tier / tier_source / last_seen_* → §8 红; 删旗子 → §3 红
  ④ 分组时把值为 None 的键当没带                → §8 红 (apply_cleared_status 故意写的 NULL 会丢)

跑法: cd scripts && python check_batch_upsert_columns.py
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import httpx
import yaml
from postgrest import SyncPostgrestClient

import annotate_essence_pass as essence
import sync_feishu_notes_to_truth_vault as engine
from _common import _REQUIRED_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://tv.invalid/rest/v1"
POSITIVE = {"爆", "大爆"}


# ── 假 PostgREST: 真 request builder, 只把最后一跳换成 MockTransport ──────────────────
class _Recorder:
    def __init__(self, *, fail_batch: bool = False, fail_ids: frozenset[str] = frozenset()):
        self.requests: list[dict] = []
        self.fail_batch = fail_batch
        self.fail_ids = fail_ids

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"null")
        rows = body if isinstance(body, list) else [body]
        cols = request.url.params.get("columns")
        self.requests.append({
            "path": request.url.path,
            "on_conflict": request.url.params.get("on_conflict"),
            "columns": None if cols is None else [c.strip('"') for c in cols.split(",")],
            "prefer": request.headers.get("prefer", ""),
            "profile": request.headers.get("content-profile"),
            "rows": rows,
        })
        if self.fail_batch and cols is not None:
            return httpx.Response(400, json={"message": "batch refused (test)"})
        if any(r.get("note_id") in self.fail_ids for r in rows):
            return httpx.Response(400, json={"message": "row refused (test)"})
        return httpx.Response(201, json=[])


class _Client:
    """upsert_notes_batch 只用 client.schema(...).table(...).upsert(...).execute()。
    supabase.Client.schema() 会新建一个不带 http_client 的 postgrest 客户端, 所以这里自己建、把
    MockTransport 接上 —— 请求的拼法(columns= / Prefer / on_conflict)仍是 postgrest-py 的原样。"""

    def __init__(self, rec: _Recorder):
        self.rec = rec

    def schema(self, name: str) -> SyncPostgrestClient:
        http = httpx.Client(base_url=BASE, transport=httpx.MockTransport(self.rec.handler))
        return SyncPostgrestClient(BASE, schema=name, http_client=http)


def violations(requests: list[dict]) -> list[tuple[str, int, list[str]]]:
    """[(列, 请求序号, 没带这一列的 note_id 前 3 个)] —— 空 = 不变式成立。"""
    bad = []
    for idx, r in enumerate(requests):
        if r["columns"] is None:          # 单行写: 没有 columns=, 没带的键不进 SET
            continue
        for c in engine.UPSERT_PROTECTED_COLS:
            if c in r["columns"]:
                missing = [row.get("note_id") for row in r["rows"] if c not in row]
                if missing:
                    bad.append((c, idx, missing[:3]))
    return bad


# ── 用真 mapping 造一批 pending_notes (main 里 upsert 之前那几步原样走) ─────────────────
def _src(mapping: dict, target: str) -> str | None:
    return next((k for k, v in mapping["field_mapping"].items() if v == target), None)


def _needles(mapping: dict) -> tuple[str | None, str | None]:
    """(判成 爆/大爆 的状态值, 判成非正例的状态值), 都取自 mapping 自己的 tier 规则。"""
    pos = neg = None
    for r in (mapping.get("tier_extraction") or {}).get("rules") or []:
        for needle in r.get("match_contains") or []:
            if r.get("tier") in POSITIVE and pos is None:
                pos = needle
            elif r.get("tier") not in POSITIVE and r.get("tier") is not None and neg is None:
                neg = needle
    return pos, neg


def _status_col(mapping: dict) -> str | None:
    te = mapping.get("tier_extraction") or {}
    return _src(mapping, "_note_for_tier" if te.get("source") == "备注字段" else "_status_raw")


def _pending(mapping: dict, records: list[tuple[str, dict]], *, full_scan: bool = True) -> list[dict]:
    pending, seen = [], set()
    for rid, fields in records:
        seen.update(fields)
        note, _metric, _und = engine.transform_row(mapping, rid, fields)
        if note.get("raw_content"):
            pending.append(note)
    if full_scan:
        for n in pending:
            n["last_seen_at"] = "2026-10-20T02:00:00+00:00"
            n["last_seen_run_id"] = "run-test"
    engine.apply_cleared_status(mapping, pending, seen)
    return pending


def _mixed_direction_records(mapping: dict) -> list[tuple[str, dict]]:
    """方向: mapping 里每个键(抬得了的 + 有子方向的) + 一个表里没有的值 + 没填(飞书不返回这一格);
    每种方向各造几行, 状态格 / 曝光格有的有、有的没有 —— 夜跑一批 500 行里就是这么混着的。"""
    content, dircol, statcol = _src(mapping, "raw_content"), _src(mapping, "_direction_raw"), _status_col(mapping)
    imp = _src(mapping, "impressions")
    pos, neg = _needles(mapping)
    dirs: list[str | None] = list((mapping.get("direction_decomposition") or {}).keys()) + ["〔表里没有的方向〕", None]
    out = []
    for i in range(3 * len(dirs)):
        d = dirs[i % len(dirs)]
        f: dict = {content: f"占位正文 {i} " * 3}
        if dircol and d is not None:
            f[dircol] = d
        if statcol and i % 3 != 2:
            f[statcol] = pos if i % 2 else (neg or pos)
        if imp and i % 4 == 0:
            f[imp] = 1000 + i
        if i == 1:      # 一行带写作台回灌的 lineage 列(R-031), 其余不带 —— 不带的行库里是写作台回填的对照
            f["_source_autowriter_item_id"] = "00000000-0000-4000-8000-000000000001"
            f["_source_autowriter_version_id"] = "00000000-0000-4000-8000-000000000002"
        out.append((f"recT{i:04d}", f))
    return out


def _mapping_ids() -> list[str]:
    return sorted(p.stem for p in (ROOT / "mappings").glob("*.yaml") if not p.stem.startswith("_"))


def _check_batch(pending: list[dict], chunk: int, label: str) -> _Recorder:
    rec = _Recorder()
    written = engine.upsert_notes_batch(_Client(rec), pending, chunk_size=chunk)
    bad = violations(rec.requests)
    assert not bad, f"{label}: 同一请求里有行没带受保护列(会被写成 NULL): {bad[:5]}"
    ids = [r["note_id"] for q in rec.requests for r in q["rows"]]
    assert sorted(ids) == sorted(n["note_id"] for n in pending), f"{label}: 每篇要正好写一次"
    assert written == {n["note_id"] for n in pending}, f"{label}: 返回值 = 写成的 note_id 集合"
    for q in rec.requests:
        assert q["path"].endswith("/notes") and q["on_conflict"] == "note_id" and q["profile"] == "truth_vault", \
            f"{label}: 请求形状不对 {q['path']} {q['on_conflict']} {q['profile']}"
        assert len(q["rows"]) <= chunk, f"{label}: 一个请求 {len(q['rows'])} 行 > chunk {chunk}"
    return rec


# ── §1 混方向批 ────────────────────────────────────────────────────────────────
def check_mixed_direction() -> dict[str, list[dict]]:
    batches: dict[str, list[dict]] = {}
    mixed_cf = []
    for pid in _mapping_ids():
        m = engine.load_mapping(pid)
        pending = _pending(m, _mixed_direction_records(m))
        assert pending, f"§1 {pid}: 一行都没造出来"
        batches[pid] = pending
        assert {("source_autowriter_version_id" in n) for n in pending} == {True, False}, \
            f"§1 {pid}: 要有一行带写作台 lineage、其余不带"
        has_cf = {("content_format" in n) for n in pending}
        if has_cf == {True, False}:
            mixed_cf.append(pid)
        for chunk in (500, 4):
            rec = _check_batch(pending, chunk, f"§1 {pid} chunk={chunk}")
            if has_cf == {True, False}:
                with_cf = [q for q in rec.requests if "content_format" in q["columns"]]
                without = [q for q in rec.requests if "content_format" not in q["columns"]]
                assert with_cf and without, f"§1 {pid}: 抬得了 / 抬不了的行要分进不同请求"
    lifting = [p for p in _mapping_ids()
               if _src(engine.load_mapping(p), "_direction_raw")
               and any("sub_directions" not in v for v in (engine.load_mapping(p).get("direction_decomposition") or {}).values())]
    assert sorted(mixed_cf) == sorted(lifting) and len(lifting) >= 10, \
        f"§1 用例要真混(否则测了个寂寞): 混了 {mixed_cf}, 应混 {lifting}"
    nuc = batches["NUC_phase1"]
    assert {("target_audience" in n) for n in nuc} == {True, False}, "§1 NUC 要同时有子方向行(不带人群)和抬得了的行"
    print(f"  §1 {len(batches)} 张真 mapping 的混方向批 (chunk 500 / 4): 受保护列同请求要么全带要么全不带, "
          f"每篇写一次; {len(mixed_cf)} 张真的混了 content_format ✓")
    return batches


# ── §2 整批 tier 翻转被挡 ──────────────────────────────────────────────────────
def check_tier_flip_blocked() -> None:
    m = engine.load_mapping("WTG_phase1")
    pos, neg = _needles(m)
    content, dircol, statcol = _src(m, "raw_content"), _src(m, "_direction_raw"), _status_col(m)
    dirs = list(m["direction_decomposition"]) + [None]
    recs = [(f"recF{i:04d}", {content: f"占位正文 {i} " * 3, statcol: pos,
                              **({dircol: dirs[i % len(dirs)]} if dirs[i % len(dirs)] else {})})
            for i in range(60)]
    pending = _pending(m, recs)
    current = {n["note_id"]: ("趴" if i < 30 else "爆") for i, n in enumerate(pending)}   # 30 篇要从 趴 升 爆
    plan = engine.plan_tier_flip(pending, current)
    assert plan["blocked"] and len(plan["flips"]) == 30, f"§2 用例要真的被挡: {len(plan['flips'])} 翻转, 阈值 {plan['threshold']}"
    assert engine.apply_tier_flip_block(pending, plan) == 30
    blocked = set(plan["flips"])
    assert {("tier" in n) for n in pending} == {True, False}, "§2 批里要同时有被剥掉 tier 的和没被剥的"
    for chunk in (500, 7):
        rec = _check_batch(pending, chunk, f"§2 chunk={chunk}")
        for q in rec.requests:
            ids = {r["note_id"] for r in q["rows"]}
            if ids & blocked:
                assert "tier" not in q["columns"] and "tier_source" not in q["columns"], \
                    "§2 被挡的篇进了带 tier 的请求 —— 库里的 tier 会被写成 NULL, 翻转闸等于没挡"
                assert ids <= blocked
            else:
                assert "tier" in q["columns"]
    print("  §2 整批翻转被挡: 被剥掉 tier 的 30 篇只进不带 tier / tier_source 的请求, 没被挡的照写 ✓")


# ── §3 状态列整轮消失 ──────────────────────────────────────────────────────────
def check_status_column_vanished() -> None:
    m = engine.load_mapping("HATHERINE_phase1")
    content, cc = _src(m, "raw_content"), _src(m, "comments_count")
    assert cc, "§3 HATHERINE 要映评论数(数值推断那条路)"
    recs = [(f"recV{i:04d}", {content: f"占位正文 {i} " * 3, **({cc: 120 if i % 2 else 60} if i % 3 == 0 else {})})
            for i in range(30)]
    pending = _pending(m, recs)
    assert engine.apply_cleared_status(m, pending, set().union(*(f for _r, f in recs))) == 0, \
        "§3 状态列一行都没返回 → apply_cleared_status 不动(交给核心列消失闸)"
    with_tier = {n["note_id"] for n in pending if "tier" in n}
    assert with_tier and len(with_tier) < len(pending) and all(
        n["tier_source"] == "数值推断" for n in pending if "tier" in n), "§3 只有过线的篇带 tier(数值推断)"
    rec = _check_batch(pending, 500, "§3")
    for q in rec.requests:
        ids = {r["note_id"] for r in q["rows"]}
        assert (ids <= with_tier) == ("tier" in q["columns"]), \
            "§3 不带 tier 的篇进了带 tier 的请求 —— 一次改名会把这些篇的 tier 刷成 NULL"
    print(f"  §3 状态列整轮消失: {len(with_tier)} 篇数值推断带 tier, 其余 {len(pending) - len(with_tier)} 篇不进带 tier 的请求 ✓")

    # §3b 同一条路上的旗子: 状态列整轮消失时 synthetic 判不出来, 只有少数行因为别的原因有旗子
    #     (置顶评论 → comment_maintained / 未来发布时间)。没旗子的行要留库里的旗子(里面可能是
    #     synthetic=true), 不能被同批有旗子的行带着冲成 NULL —— tier 留着、限定词没了, 伪爆贴就成了真爆款。
    m = engine.load_mapping("NUC_phase1")
    content, pin, pub = _src(m, "raw_content"), _src(m, "pinned_comment"), _src(m, "publish_time")
    assert pin and pub, "§3b NUC 要映置顶评论和发布时间"
    recs = []
    for i in range(12):
        f = {content: f"占位正文 {i} " * 3}
        if i == 2:
            f[pin] = "置顶了"
        if i == 5:
            f[pub] = "2099-01-01 00:00:00"
        recs.append((f"recW{i:04d}", f))
    pending = _pending(m, recs)
    flagged = {n["note_id"] for n in pending if "data_quality_flags" in n}
    assert len(flagged) == 2 and all("tier" not in n for n in pending), \
        f"§3b 用例: 状态列整轮没出现、只有 2 篇有旗子 (实际 {len(flagged)})"
    rec = _check_batch(pending, 500, "§3b")
    for q in rec.requests:
        ids = {r["note_id"] for r in q["rows"]}
        assert (ids <= flagged) == ("data_quality_flags" in q["columns"]), "§3b 没旗子的篇进了带旗子的请求"
    print("  §3b 同一条路上的旗子: 只有 2 篇判出旗子, 其余 10 篇不进带 data_quality_flags 的请求 ✓")


# ── §8 名单逐列 ────────────────────────────────────────────────────────────────
# 每一列的证据写在 UPSERT_PROTECTED_COLS 上面的注释和 D-122 里。多加可以, 少一列就红:
# 删之前先在 DECISIONS 里写清楚为什么那一列「没带」可以被冲成 NULL。
MUST_PROTECT = frozenset({
    "content_format", "target_audience", "user_pain_point", "product_focus",   # essence 也写
    "tier", "tier_source",                                                      # 翻转闸 / 状态列消失故意不写
    "data_quality_flags",                                                        # tier 的限定词
    "source_autowriter_item_id", "source_autowriter_version_id",                # 写作台回填
    "last_seen_at", "last_seen_run_id",                                          # 部分同步不盖戳
})


def check_each_protected_col() -> None:
    lost = MUST_PROTECT - set(engine.UPSERT_PROTECTED_COLS)
    assert not lost, f"§8 名单少了 {sorted(lost)} —— 这些列没带时会被同批的行带着冲成 NULL"
    for c in engine.UPSERT_PROTECTED_COLS:
        pending = [{"note_id": "P_a", "raw_content": "x", c: None},
                   {"note_id": "P_b", "raw_content": "x"},
                   {"note_id": "P_c", "raw_content": "x", c: None}]
        rec = _check_batch(pending, 500, f"§8 {c}")
        assert len(rec.requests) == 2, f"§8 {c}: 带(哪怕是 None)/ 不带要分成两个请求"
    print(f"  §8 名单 {len(engine.UPSERT_PROTECTED_COLS)} 列一列不少; 逐列带(哪怕是 None)/ 不带分进两个请求 ✓")


# ── §4 镜像口径保留 ────────────────────────────────────────────────────────────
def check_mirror_kept(batches: dict[str, list[dict]]) -> None:
    mirrored = 0
    for pid, pending in batches.items():
        rec = _Recorder()
        engine.upsert_notes_batch(_Client(rec), pending, chunk_size=500)
        groups = engine._group_by_protected_cols(pending)
        assert len(rec.requests) == sum(math.ceil(len(g) / 500) for g in groups), \
            f"§4 {pid}: 请求数要等于按受保护列分的组数 —— 多了说明按完整键集分了, 镜像飞书的口径被顺手改掉"
        for q in rec.requests:
            if "impressions" in q["columns"] and any("impressions" not in r for r in q["rows"]):
                mirrored += 1
    assert mirrored >= 5, f"§4 指标格子没带的行要照旧和带的行同批(= 写成 NULL, 跟飞书一致), 只见到 {mirrored} 个请求"
    assert "impressions" not in engine.UPSERT_PROTECTED_COLS
    print(f"  §4 镜像口径: 不按完整键集分组, {mirrored} 个请求里曝光格子没带的行照旧同批写 NULL ✓")


# ── §5 名单本身 ────────────────────────────────────────────────────────────────
class _Chain:
    def __init__(self):
        self.update_payload: dict | None = None

    def schema(self, *_):
        return self

    def table(self, *_):
        return self

    def update(self, payload):
        self.update_payload = dict(payload)
        return self

    def eq(self, *_):
        return self

    def execute(self):
        return None


def check_protected_list(batches: dict[str, list[dict]]) -> None:
    prot = set(engine.UPSERT_PROTECTED_COLS)
    assert len(prot) == len(engine.UPSERT_PROTECTED_COLS), "§5 名单里有重复"
    unknown = prot - set(_REQUIRED_COLUMNS["notes"])
    assert not unknown, f"§5 名单里有 notes 没有的列(拼错了 = 那一列静默不受保护): {unknown}"

    direct = []
    for p in sorted((ROOT / "mappings").glob("*.yaml")):
        fm = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("field_mapping") or {}
        direct += [f"{p.stem}:{col}→{t}" for col, t in fm.items() if t in prot]
    assert not direct, (f"§5 飞书格子直接映到了受保护列: {direct}。受保护 = 没带就留库值, 飞书清空格子将不再"
                        "清库; 要么别直接映, 要么把这一列从 UPSERT_PROTECTED_COLS 摘掉并在 D 号里写清楚")

    assert set(engine._LINEAGE_FK_COLS.values()) <= prot, "§5 写作台回填的 lineage 两列要在名单里"

    sync_keys = set().union(*(set(n) for b in batches.values() for n in b))
    ch = _Chain()
    parsed = {"essence": {"emotional_lever": "x", "emotional_valence": "x", "emotional_intensity": "x",
                          "human_truth_archetype": "x", "trend_dependencies": [], "content_format": "x"},
              "audience": {}}
    subs = [{"name": "S", "content_format": "a", "target_audience": "b", "user_pain_point": "c", "product_focus": "d"}]
    essence.write_essence_back(ch, "P_rec1", "m", parsed, ("S", subs), dry_run=False)
    shared = (set(ch.update_payload) & sync_keys) - prot
    assert not shared, f"§5 essence 写、夜跑同步也写的列不在名单里(混批会被冲掉): {shared}"
    assert {"content_format", "target_audience", "user_pain_point", "product_focus"} <= set(ch.update_payload)
    print(f"  §5 名单 {len(prot)} 列都是 notes 的真列; 没有 mapping 直接映它们; essence / 写作台与同步共写的列都在 ✓")


# ── §6 反证 ────────────────────────────────────────────────────────────────────
def check_counterproof(batches: dict[str, list[dict]]) -> None:
    nuc = batches["NUC_phase1"]
    rec = _Recorder()
    _Client(rec).schema("truth_vault").table("notes").upsert(nuc, on_conflict="note_id").execute()
    q = rec.requests[0]
    assert "resolution=merge-duplicates" in q["prefer"] and "content_format" in q["columns"], \
        "§6 机制: 老写法一个请求、columns= 里有 content_format、冲突即更新"
    cols = {c for c, _i, _ids in violations(rec.requests)}
    assert {"content_format", "target_audience"} <= cols, f"§6 老写法必须被判红(NUC 两列都会被冲掉): {cols}"

    saved = engine.UPSERT_PROTECTED_COLS
    engine.UPSERT_PROTECTED_COLS = ()
    try:
        rec2 = _Recorder()
        engine.upsert_notes_batch(_Client(rec2), nuc)
    finally:
        engine.UPSERT_PROTECTED_COLS = saved
    assert violations(rec2.requests), "§6 名单清空后 upsert_notes_batch 必须被判红(这道检查不是空转)"
    print("  §6 反证: 老写法整批一把 upsert → 红(content_format / target_audience); 名单清空 → 红 ✓")


# ── §7 逐行兜底 / dry-run 照旧 ────────────────────────────────────────────────
def check_fallback_unchanged(batches: dict[str, list[dict]]) -> None:
    pending = batches["RIO_phase1"]
    bad_id = pending[3]["note_id"]
    rec = _Recorder(fail_batch=True, fail_ids=frozenset({bad_id}))
    lg = engine.logger
    level = lg.level
    lg.setLevel(logging.CRITICAL)        # 逐行失败的 traceback / dry-run 每篇一行是故意的, 不刷屏
    try:
        written = engine.upsert_notes_batch(_Client(rec), pending, chunk_size=6)
        rec2 = _Recorder()
        ids = engine.upsert_notes_batch(_Client(rec2), pending, dry_run=True)
    finally:
        lg.setLevel(level)
    assert written == {n["note_id"] for n in pending} - {bad_id}, "§7 批被拒 → 逐行补, 只有逐行也失败的那篇不在返回值里"
    singles = [q for q in rec.requests if q["columns"] is None]
    assert len(singles) == len(pending) and all(len(q["rows"]) == 1 for q in singles), \
        "§7 逐行兜底: 每篇一个单行请求, 不带 columns=(所以兜底路径本来就没这个问题)"
    assert not violations(rec.requests)

    assert ids == {n["note_id"] for n in pending} and not rec2.requests, "§7 dry-run 不发请求、返回全部 id"
    print("  §7 逐行兜底: 批被拒逐行补、单行不带 columns=、失败篇不进返回值; dry-run 不发请求 ✓")


def main() -> int:
    batches = check_mixed_direction()
    check_tier_flip_blocked()
    check_status_column_vanished()
    check_mirror_kept(batches)
    check_protected_list(batches)
    check_counterproof(batches)
    check_fallback_unchanged(batches)
    check_each_protected_col()
    print("\ncheck_batch_upsert_columns: 8 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
