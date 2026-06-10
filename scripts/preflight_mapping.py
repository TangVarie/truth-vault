#!/usr/bin/env python3
"""
preflight_mapping.py — 接新表前的【只读体检】(不写库、不调 LLM/worker)。

接新表 SOP 第一步: 在真跑 `Daily TV sync` 前先跑这个, 把"会 quarantine 多少 / 哪些列没声明 /
品类是否合法 / tier·intent·方向分布"在几秒内报出来 —— 数据形状的意外当场看见、改完 mapping
再真跑。把过去"在 prod 真跑→看炸什么→修"收敛成"接表前一键体检"。

为什么需要它: 历次接表(NRT_2 / NUC)反复踩的"便宜就能提前抓"的坑都在【数据形状】层:
  · 漏声明列 → D-021 整行 quarantine(NRT_2 曾因此丢 482 行真内容)
  · 品类不在受控闭集 → sync 第一条 INSERT 撞 notes.category CHECK(R-009)
  · 方向不在 direction_decomposition → 拿不到 content_format/audience/子方向
  · intent_mapping 没覆盖 → intent 全 'other'
本脚本一次性把这些在【不写库、不花 LLM】的前提下投影出来。

复用真 sync 的 transform_row + FeishuClient ⇒ 投影 100% 与真跑一致; 但:
  - 不创建 Supabase client, 不写 notes / metric_snapshots / quarantine。
  - 不调 worker / LLM(essence / sub_direction 分类不在此跑 —— 那是富集层, 与数据形状无关)。

用法 : python preflight_mapping.py <project_id> [--limit N] [--show N]
环境 : FEISHU_APP_ID / FEISHU_APP_SECRET(只读飞书)。【不需要】Supabase / worker 任何凭据。
退出 : 0 = 无阻断问题(可真跑); 1 = 有该先修的问题(未声明列丢真内容 / 品类非法); 2 = 用法/配置错。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from _common import load_mapping, resolve_feishu_tables, _direction_key
from sync_feishu_notes_to_truth_vault import (
    FeishuClient,
    transform_row,
    _LINEAGE_COLS,
    _NOTE_DATA_SIGNALS,
)

# 受控品类闭集 —— 权威是 schemas/notes_v1_2.sql 的 notes.category CHECK(也见 onboarder/vocab.py)。
# 新表 category 必须在此集内, 否则 sync 第一条 INSERT 就撞 CHECK(NRT_2 上线踩过, R-009)。
CATEGORIES = {
    "处方药", "OTC药", "保健品", "医疗器械", "美妆", "个护", "酒类",
    "食品饮料", "母婴", "3C数码", "家居家电", "服饰鞋包", "教育", "其他",
}
# 飞书 API 总会带的控制键(非用户列), 不算"未声明" —— 与 transform_row 内的同名集合保持一致。
_IGNORED_META_KEYS = {"_record_id", "_created_time", "_last_modified_time"}
_VALID_TIER_SOURCES = {"状态字段", "备注字段"}


def _hr(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 52 - len(title)))


def project_rows(mapping: dict, records, show_cap: int) -> dict:
    """对每条飞书 record 跑 transform_row(不写库), 聚合成体检报告需要的统计。

    `records` 是可迭代的飞书 item(dict, 含 record_id + fields)—— 真跑用
    FeishuClient.list_records, 测试可传合成列表。返回一个 stats dict。
    """
    fm = mapping.get("field_mapping") or {}
    raw_extra_allow = set(mapping.get("project_specific_fields_to_raw_extra", []))
    declared = set(fm) | raw_extra_allow | set(_LINEAGE_COLS)
    dirdecomp = mapping.get("direction_decomposition") or {}
    excluded_dirs = {e.get("direction") for e in (mapping.get("excluded_directions") or [])}
    dir_col = next((k for k, v in fm.items() if v == "_direction_raw"), None)
    status_cols = {k for k, v in fm.items() if v == "_status_raw"}        # tier 源列(可多张表多列)
    note_status_cols = {k for k, v in fm.items() if v == "_note_status_raw"}  # 伪爆贴检测列(含「关注」)

    def _flatval(x):
        return " / ".join(map(str, x)) if isinstance(x, list) else str(x)

    s = {
        "n": 0,
        "present_cols": Counter(),         # 表里出现过的列 → 行数
        "undeclared_cols": Counter(),      # 未声明列 → 行数
        "undeclared_with_content": Counter(),  # 未声明列 ∩ 该行有正文(=真笔记会被整行 quarantine)
        "proj": Counter(),                 # upsert / q_undeclared / q_empty / q_anomaly / error
        "tiers": Counter(),
        "tier_src": Counter(),
        "intents": Counter(),
        "dirs_seen": Counter(),
        "dirs_missing": Counter(),
        "status_vals": Counter(),          # tier 源列原始取值分布(看「伪爆贴」等是否在 tier 源里)
        "note_status_vals": Counter(),     # 笔记状态原始取值分布(看「关注」伪爆贴标记是否存在)
        "has_dir_col": dir_col is not None,
        "declared": declared,
        "fm_and_allow": set(fm) | raw_extra_allow,
    }

    for item in records:
        s["n"] += 1
        rid = item.get("record_id", "")
        raw = item.get("fields", {}) or {}
        for k in raw:
            if k not in _IGNORED_META_KEYS:
                s["present_cols"][k] += 1
        for col in status_cols:
            if col in raw and raw[col] not in (None, ""):
                s["status_vals"][_flatval(raw[col])] += 1
        for col in note_status_cols:
            if col in raw and raw[col] not in (None, ""):
                s["note_status_vals"][_flatval(raw[col])] += 1
        try:
            note, _metric, undeclared = transform_row(mapping, rid, raw)
        except Exception as exc:  # 真 sync 也是 try/except 计 errors; 这里同样不让一行毁报告
            s["proj"]["error"] += 1
            if s["proj"]["error"] <= show_cap:
                print(f"  ⚠️ transform 异常 record_id={rid}: {exc!r}")
            continue

        has_content = bool(note.get("raw_content"))
        if undeclared:  # 真 sync: undeclared 优先于缺正文判 → 整行 quarantine
            for c in undeclared:
                s["undeclared_cols"][c] += 1
                if has_content:
                    s["undeclared_with_content"][c] += 1
            s["proj"]["q_undeclared"] += 1
            continue
        if not has_content:  # 缺 raw_content → 空占位(静默)vs 真异常(有 note 信号)
            is_empty = not any(note.get(k) for k in _NOTE_DATA_SIGNALS)
            s["proj"]["q_empty" if is_empty else "q_anomaly"] += 1
            continue

        # 会入库的行: 收分布
        s["proj"]["upsert"] += 1
        s["tiers"][note.get("tier") or "(未定)"] += 1
        if note.get("tier_source"):
            s["tier_src"][note["tier_source"]] += 1
        if note.get("intent"):
            s["intents"][note["intent"]] += 1
        if dir_col is not None:
            rawdir = (note.get("raw_extra") or {}).get("_direction_raw")
            dk = _direction_key(rawdir) if rawdir is not None else ""
            if dk:
                s["dirs_seen"][dk] += 1
                if dk not in dirdecomp and dk not in excluded_dirs:
                    s["dirs_missing"][dk] += 1
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="接新表前只读体检(不写库、不调 LLM)")
    ap.add_argument("project_id")
    ap.add_argument("--limit", type=int, default=0, help="只看前 N 行(调试; 0=全表)")
    ap.add_argument("--show", type=int, default=8, help="清单(未声明列/缺方向等)最多展示几项")
    args = ap.parse_args()

    blocking: list[str] = []
    warnings: list[str] = []

    # ── 1. 静态 mapping 检查(不连飞书)──
    _hr(f"1. mapping 静态检查 · {args.project_id}")
    try:
        mapping = load_mapping(args.project_id)
    except Exception as exc:  # load_mapping 会校验 tier_extraction.source 等 → 坏的直接报
        print(f"  ❌ 加载/校验 mapping 失败: {exc}")
        return 2
    print(f"  project={mapping.get('project_id')} brand={mapping.get('brand')} "
          f"product={mapping.get('product')}")
    print(f"  schema_family={mapping.get('schema_family')} platform={mapping.get('platform')}")

    category = mapping.get("category")
    if category in CATEGORIES:
        print(f"  ✅ category={category!r} 在受控闭集内")
    else:
        print(f"  ❌ category={category!r} 不在受控闭集 → sync 会撞 notes.category CHECK")
        print(f"     合法值: {sorted(CATEGORIES)}")
        blocking.append(f"category={category!r} 非法")

    tsrc = (mapping.get("tier_extraction") or {}).get("source")
    if tsrc:
        print(f"  {'✅' if tsrc in _VALID_TIER_SOURCES else '⚠️'} tier_extraction.source={tsrc!r}")

    fm = mapping.get("field_mapping") or {}
    if any(v == "_intent_raw" for v in fm.values()) and not mapping.get("intent_mapping"):
        print("  ⚠️ field_mapping 映了 _intent_raw 但缺 intent_mapping → intent 多半全 'other'")
        warnings.append("缺 intent_mapping")

    sc = mapping.get("sync_config") or {}
    # 多表合并(sync_config.tables)时逐表都体检 —— 列覆盖/分布在所有表上聚合, 否则只查
    # 第一张表会漏掉第二张表的未声明列(D-021 整行 quarantine 丢真笔记)。
    specs = resolve_feishu_tables(sc)
    configured = [sp for sp in specs if sp["app_token"] and sp["table_id"]]
    if not configured:
        print("  ❌ sync_config 缺 feishu_app_token / feishu_table_id → 还没 onboard, 无法读表")
        return 2
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("  ❌ 需设环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET(只读飞书)")
        return 2

    # ── 2. 读飞书(只读)+ 逐行投影 ──
    _hr("2. 读飞书 + 投影(transform_row, 不写库/不调 LLM)")
    if len(configured) > 1:
        print(f"  多表合并: {len(configured)} 张飞书表 → 同一 project(列覆盖/分布在所有表上聚合)")
    fs = FeishuClient(app_id, app_secret)

    def _iter_all_records():
        for sp in configured:
            yield from fs.list_records(sp["app_token"], sp["table_id"], sp["view_id"])

    records = _iter_all_records()
    if args.limit:
        records = (r for i, r in enumerate(records) if i < args.limit)
    s = project_rows(mapping, records, args.show)
    print(f"  读到 {s['n']} 行")
    if s["n"] == 0:
        print("  ⚠️ 表里 0 行 —— app_token/table_id 对吗?机器人是协作者吗?")
        warnings.append("表 0 行")

    # ── 3. 列覆盖 ──
    _hr("3. 列覆盖")
    if s["undeclared_cols"]:
        n_lost = sum(s["undeclared_with_content"].values())
        print(f"  ⚠️ 未声明列 {len(s['undeclared_cols'])} 个(出现即【整行 quarantine】, D-021):")
        for c, cnt in s["undeclared_cols"].most_common(args.show):
            wc = s["undeclared_with_content"].get(c, 0)
            tag = (f"  ❌ 其中 {wc} 行有正文 = 真笔记会丢!" if wc else "  (仅空行)")
            print(f"      · {c!r}: {cnt} 行{tag}")
        if len(s["undeclared_cols"]) > args.show:
            print(f"      … 余 {len(s['undeclared_cols']) - args.show} 个")
        print(f"     → 修: 加进 mappings/{args.project_id}.yaml 的 "
              f"project_specific_fields_to_raw_extra")
        if n_lost:
            blocking.append(f"{len(s['undeclared_cols'])} 个未声明列(共 {n_lost} 行有正文会丢)")
        else:
            warnings.append(f"{len(s['undeclared_cols'])} 个未声明列(仅空行, 不丢真内容)")
    else:
        print("  ✅ 无未声明列(所有列都已 field_mapping 或 raw_extra 声明)")

    declared_absent = sorted(s["fm_and_allow"] - set(s["present_cols"]))
    if declared_absent:
        print(f"  ⚠️ 声明了但表里没有的列(拼错/改名/本期无数据?): {declared_absent[:args.show]}")
        warnings.append("有声明列在表中缺失")

    # ── 4. 入库投影 ──
    _hr("4. 入库投影")
    p = s["proj"]
    print(f"  ✅ 会入库(有正文)         : {p['upsert']}")
    print(f"  ⏭  空占位/评论碎片(静默)   : {p['q_empty']}")
    if p["q_anomaly"]:
        print(f"  ⚠️ 缺正文但有 note 信号(逐条告警的真异常): {p['q_anomaly']}")
    if p["q_undeclared"]:
        print(f"  ❌ 因未声明列被整行 quarantine: {p['q_undeclared']}")
    if p["error"]:
        print(f"  ❌ transform 异常行: {p['error']}")
        blocking.append(f"{p['error']} 行 transform 异常")

    # ── 5. 分布(会入库的行)──
    _hr("5. 分布(会入库的行)")
    bao = s["tiers"].get("爆", 0) + s["tiers"].get("大爆", 0)
    print(f"  tier        : {dict(s['tiers'].most_common())}  → 爆+大爆(燃料)={bao}")
    print(f"  tier_source : {dict(s['tier_src'].most_common())}")
    if s["status_vals"]:
        print(f"  tier源原始取值 : {dict(s['status_vals'].most_common(args.show))}")
        # 伪爆贴若藏在 tier 源里(如「伪爆贴」含子串「爆贴」会被误读成 爆)→ 提示
        if any("伪爆" in v for v in s["status_vals"]):
            print("     ⚠️ tier 源里出现「伪爆」字样 —— 注意 tier 规则 match_contains 顺序(伪爆贴含「爆贴」会误判成 爆!),且应判 synthetic")
            warnings.append("tier 源含「伪爆贴」(需 tier 规则前置 + 判 synthetic)")
    if s["note_status_vals"]:
        print(f"  笔记状态取值 : {dict(s['note_status_vals'].most_common(args.show))}")
        print(f"     含「关注」(伪爆贴标记)行数 = {sum(c for v, c in s['note_status_vals'].items() if '关注' in v)}")
    print(f"  intent      : {dict(s['intents'].most_common())}")
    if s["intents"].get("other"):
        print(f"     ⚠️ intent='other' {s['intents']['other']} 行(发布笔记里有 "
              f"intent_mapping 没覆盖的取值)")
        warnings.append("有 intent=other")
    if s["has_dir_col"]:
        if s["dirs_missing"]:
            print(f"  ⚠️ 方向不在 direction_decomposition({len(s['dirs_missing'])} 种 —— "
                  f"这些行拿不到 content_format/audience/子方向):")
            for d, c in s["dirs_missing"].most_common(args.show):
                print(f"      · {d!r}: {c} 行")
            warnings.append(f"{len(s['dirs_missing'])} 种方向未在 mapping 拆解")
        else:
            print(f"  ✅ 方向全部命中 decomposition/excluded({len(s['dirs_seen'])} 种)")

    # ── 裁决 ──
    _hr("裁决")
    if blocking:
        print("  ❌ 该先修的阻断问题:")
        for b in blocking:
            print(f"      - {b}")
    if warnings:
        print("  ⚠️ 提醒(不阻断, 心里有数):")
        for w in warnings:
            print(f"      - {w}")
    if not blocking and not warnings:
        print("  ✅ 干净 —— 可以真跑 Daily TV sync(全名 project, 先 dry_run)。")
    elif not blocking:
        print("  ✅ 无阻断问题 —— 可以真跑(留意上面提醒)。")
    else:
        print("  → 建议先按上面改 mapping, 再真跑。")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
