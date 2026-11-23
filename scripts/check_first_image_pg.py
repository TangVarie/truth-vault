#!/usr/bin/env python3
"""schemas/notes_v1_28_first_image.sql 在真 Postgres 上的夹具与反证 (D-158; ci.yml sql job 调, 迁移已经跑过两遍之后)。
只在一次性的本地库上跑 (tv_ci 之类); 夹具全是合成的 (CI_V28 前缀), 最后删干净。走 psql, 只用标准库。

  A 段 (只用标准库, 一定跑):
    · 取列: 内容配图 > 笔记配图 > 图片, 取第 0 个带 file_token 的附件; 不是数组、没有 token 的不算; 指纹 = sha256(file_token)
    · 这一晚该做哪些: 经验卡的帖 + 新入库的帖; 老帖不出; 先不做的项目、飞书里已删的帖不出; 只要经验卡的帖时只出经验卡的帖;
      做过的不再出, 图换了 / 到了重试时间再出; 经验卡的帖排前面
    · 整张表刚接进来 (所有帖的入库时刻都是当天): 发布超过 30 天的、没有发布时间的都不算新帖; 刚发布的算; 经验卡的帖照出
    · 写结果: 不是封面只许带 img_kind 一行; 答完了必须有 img_kind = 封面; 别的 run_tag、别的帖的行被拒;
      重写一篇先删它旧的首图答案, 文字题库的行 (run_tag = primary) 不动
    · 重试: 算数的失败 3 次、或一共试 6 次之后不再自动试; 换了图从头算
    · 读的那一面: 题库镜像那一行不在时没有一篇能用; 多图的帖在项目被确认之前 answers 是 NULL, 确认之后不用重写就放开;
      项目被列为先不做 → 不能用; answers 只出往外给的题里答成了的; 抄下来的字不出;
      做完之后运营又加了图 (第一个附件没变, 不会重做) → n_files 和 cover_unconfirmed 立刻跟着变, 不能用;
      做完之后首图换了或图片列没了 → image_changed, 不能用
    · scripts/verify_supabase_state.sql #87 (同一跑里行数不齐 = 半写) 不因为「不是封面只存一行」多数出来
    · 权限: anon / authenticated 什么都没有; service_role 调得动三个函数、读得到那张视图
  B 段 (要 pyyaml; 没有就跳过并打一条 ::warning::): 用 scripts/first_image_pass.py 真跑一趟 (假下载、假缩图、假模型, 库是真的),
    再跑一趟确认不重复做、不重复问。排第一的经验卡帖飞书不给下载: 记一笔、别的照做, 到了重试时间再试也卡不住别的帖。
    其中一篇答案自相矛盾 (说了没有字、又抄出了字; D-160): 库收下带 inconsistent:<规则名> 的行, 这一篇是 answered、13 行、
    读的那一面 usable = true, answers 里没有 img_text_kind 和 img_text_has_number (没有键 = 没答成; fi-v0.3 里这两道本来就不往外给,
    作废了几道看库里那几行的原因), 别的往外给的题照有。
    一篇说了有字、大字是空的、版式是纯文字卡片: answers 里连 img_layout 也没有。一篇说了没有字、抄出来的是「没有」
    (said_none_in_words, 两次说的是一回事): 照旧 no_answer、一行答案都不写、按日程重问。

反证 (改坏迁移之后必须红):
    · v_note_first_image_source 的 ORDER BY k.ord 去掉或调换                       → 取列
    · first_image_candidates 去掉 v_notes_vanished / p_excluded 那一行             → 该做哪些
    · write_first_image_result 去掉先删旧答案那一句                                → 「换了图之后旧答案还在」
    · v_first_image_features 的 usable 去掉 NOT g.cover_unconfirmed                → 「多图没确认不能用」
    · v_first_image_features 的 n_files 改回读状态表里记的数 (s.n_files)            → 「做完之后又加了图」
    · v_first_image_features 的 usable 去掉 NOT cur.image_changed                  → 「图片列没了 / 首图换了」
    · first_image_candidates 去掉发布时间那几行 (只看 ingested_at)                  → 「整张表刚接进来」
    · verify_supabase_state.sql #87 去掉 run_tag NOT LIKE 'img-%'                  → #87
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PSQL = ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
P1, PX, PN = "CI_V28", "CI_V28_X", "CI_V28_N"
BANK_V = "fi-v0.2"
# 「新帖从哪天算」直接读步骤里的那个常量 (只用标准库, 不 import: A 段在没有 pyyaml 的环境也要跑): 有人把它改早, 下面「老帖不出」就红
SINCE = re.search(r'^NEW_SINCE = "([^"]+)"', (HERE / "first_image_pass.py").read_text(encoding="utf-8"), re.M).group(1)
ALL_P = f"('{P1}','{PX}','{PN}')"


def sql(text: str, *, ok: bool = True) -> str:
    res = subprocess.run(PSQL, input=text, text=True, capture_output=True, timeout=60)
    if ok and res.returncode:
        raise AssertionError(res.stderr[-800:])
    if not ok:
        assert res.returncode != 0, f"这句本该被拒: {text[:200]}"
        return res.stderr
    return res.stdout.strip()


def J(obj) -> str:
    """Python 对象 → SQL 里的 jsonb 字面量。"""
    return "$j$" + json.dumps(obj, ensure_ascii=False) + "$j$::jsonb"


def arr(items) -> str:
    return "ARRAY[" + ",".join("'" + i + "'" for i in items) + "]::text[]"


def tok(tag: str) -> str:
    return f"boxcnCIV28{tag}"


def f(tag: str, typ: str = "image/jpeg", size: int = 1000) -> dict:
    return {"file_token": tok(tag), "name": f"{tag}.jpg", "size": size, "type": typ,
            "url": f"https://open.feishu.cn/open-apis/drive/v1/medias/{tok(tag)}/download", "tmp_url": "x"}


def sha(tag: str) -> str:
    return hashlib.sha256(tok(tag).encode()).hexdigest()


def cleanup() -> None:
    sql(f"""
        DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE '{P1}%';
        DELETE FROM truth_vault.first_image_bank_state;
        DELETE FROM truth_vault.note_sync_presence WHERE project_id IN {ALL_P};
        DELETE FROM truth_vault.notes WHERE project_id IN {ALL_P};
        DELETE FROM truth_vault.note_sync_runs WHERE project_id IN {ALL_P};
        DELETE FROM truth_vault.audit_log WHERE row_id LIKE '{P1}%';
        DELETE FROM truth_vault.projects WHERE project_id IN {ALL_P};""")


def note(nid: str, project: str, raw_extra: dict, *, new: bool, card: bool = False, publish: str | None = None,
         ing: str | None = None) -> str:
    """publish / ing: 发布时间、入库时刻的 SQL 表达式。不给 publish = 经验卡的帖 2026-10-01, 别的帖没有发布时间 (运营刚建的行)。"""
    pub = publish or ("'2026-10-01'" if card else "NULL")
    tier = f"'爆', '状态字段', {pub}" if card else f"'趴', '状态字段', {pub}"
    ing = ing or ("now()::timestamp" if new else "'2026-01-01'")
    return (f"INSERT INTO truth_vault.notes (note_id, project_id, raw_content, title, tier, tier_source, publish_time, "
            f"ingested_at, raw_extra) VALUES ('{nid}', '{project}', '合成正文', '合成标题', {tier}, {ing}, {J(raw_extra)});")


def cands(cards_only: bool = False, limit: str = "100", excluded=(PX,)) -> list[dict]:
    out = sql(f"SELECT to_jsonb(c) FROM truth_vault.first_image_candidates('{BANK_V}', '{SINCE}', {arr(excluded)}, "
              f"{'true' if cards_only else 'false'}, {limit}) c WHERE c.note_id LIKE '{P1}%';")
    return [json.loads(line) for line in out.splitlines() if line]


def state(nid: str, tag: str, status: str, outcome: str, n_files: int = 1, col: str = "内容配图", project: str = P1) -> dict:
    return {"note_id": nid, "project_id": project, "source_column": col, "file_sha": sha(tag), "n_files": n_files,
            "file_kind": "jpeg", "file_bytes": 1000, "width": 768, "height": 1024, "status": status, "outcome": outcome,
            "bank_version": BANK_V, "bank_sha256": "s" * 64, "model": "claude-haiku-5-5"}


def row(nid: str, qid: str, answer, **kw) -> dict:
    r = {"subject_type": "note", "subject_id": nid, "question_id": qid, "question_version": 1, "bank_version": BANK_V,
         "bank_sha256": "s" * 64, "extractor": "llm:claude-haiku-5-5", "run_tag": "img-primary", "answer": answer,
         "invalid_reason": None if answer is not None else "out_of_vocab"}
    r.update(kw)
    return r


def write(st: dict, rows: list, *, ok: bool = True) -> str:
    return sql(f"SELECT truth_vault.write_first_image_result({J(st)}, {J(rows)});", ok=ok)


def view(nid: str) -> dict:
    out = sql(f"SELECT to_jsonb(v) FROM truth_vault.v_first_image_features v WHERE note_id = '{nid}';")
    return json.loads(out) if out else {}


def sync(confirmed=(), excluded=(PX,), surfaced=("img_layout", "img_person")) -> None:
    sql(f"SELECT truth_vault.sync_first_image_bank('{BANK_V}', '{'s' * 64}', {arr(confirmed)}, {arr(excluded)}, {arr(surfaced)});")


COVER_ROWS = lambda nid: [row(nid, "img_kind", "封面"), row(nid, "img_layout", "一张照片"), row(nid, "img_person", None),  # noqa: E731
                          row(nid, "img_scene", "生活场景"), row(nid, "img_main_text", "合成的封面大字")]


def verify_87() -> int:
    """verify_supabase_state.sql #87 那一句, 原样抠出来跑。"""
    m = re.search(r"SELECT '87'.*?\$q\$(.*?)\$q\$", (HERE / "verify_supabase_state.sql").read_text(encoding="utf-8"), re.S)
    assert m, "verify_supabase_state.sql 里找不到 #87"
    return int(sql(m.group(1) + ";"))


def part_a() -> None:
    a, b, c, d, e, g, h = [f"{P1}_{k}" for k in "abcdegh"]
    base_87 = verify_87()
    xid = f"{PX}_x"
    sql(f"INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('{P1}', 'b', 'p', '保健品'), ('{PX}', 'b', 'p', '保健品');"
        + note(a, P1, {"内容配图": [f("a1")]}, new=False, card=True)
        + note(b, P1, {"笔记配图": [f("b1"), f("b2")]}, new=True)
        + note(c, P1, {"图片": [f("c1")]}, new=False)
        # 更早的一篇 (没有图): 有了它, 老帖 c 不出就只能是因为 NEW_SINCE —— 不是因为「项目里没有更早的帖」那一条
        + note(f"{P1}_o", P1, {}, new=False, ing="'2025-06-01'")
        + note(d, P1, {"内容配图": [], "笔记配图": [{"name": "没有 token"}, "不是对象", f("d1")], "图片": [f("d9")]}, new=True)
        + note(e, P1, {"相关截图": [f("e1")]}, new=True)
        + note(xid, PX, {"内容配图": [f("x1")]}, new=True, card=True)
        + note(g, P1, {"内容配图": [f("g1")]}, new=True)
        + note(h, P1, {"内容配图": "不是数组", "笔记配图": None, "图片": [f("h1"), f("h2"), f("h3")]}, new=True))
    # g: 飞书里已删 (上一轮完整扫描见过它, 最近一轮没见到)
    sql(f"SELECT truth_vault.begin_note_sync('{P1}', '{P1}_run1'); SELECT truth_vault.complete_note_sync('{P1}_run1', {arr([a, b, c, d, e, g, h])});"
        f"SELECT truth_vault.begin_note_sync('{P1}', '{P1}_run2'); SELECT truth_vault.complete_note_sync('{P1}_run2', {arr([a, b, c, d, e, h])});")
    assert sql(f"SELECT note_id FROM truth_vault.v_notes_vanished WHERE project_id = '{P1}';") == g, "夹具: g 应该算已删"

    # ── 取列 ──
    src = {r["note_id"]: r for r in map(json.loads, sql(
        f"SELECT to_jsonb(s) FROM truth_vault.v_note_first_image_source s WHERE note_id LIKE '{P1}%';").splitlines())}
    assert set(src) == {a, b, c, d, xid, g, h}, f"没有首图的帖不该出行: {sorted(src)}"
    want = {a: ("内容配图", 1, "a1"), b: ("笔记配图", 2, "b1"), c: ("图片", 1, "c1"), d: ("笔记配图", 1, "d1"), h: ("图片", 3, "h1")}
    for nid, (col, n, tag) in want.items():
        r = src[nid]
        assert (r["source_column"], r["n_files"], r["first_file"]["file_token"], r["file_sha"]) == (col, n, tok(tag), sha(tag)), (nid, r)

    # ── 这一晚该做哪些 ──
    got = [r["note_id"] for r in cands()]
    assert got[0] == a and set(got) == {a, b, d, h}, f"经验卡的帖在前; 老帖 c、先不做的项目、已删的 g 不出: {got}"
    assert [r["note_id"] for r in cands(cards_only=True)] == [a] and [r["note_id"] for r in cands(limit="1")] == [a]
    assert cands(limit="NULL") == [] and cands(limit="-5") == []
    first = cands()[0]
    assert first["is_card"] is True and first["title"] == "合成标题" and first["first_file"]["file_token"] == tok("a1")
    assert xid in [r["note_id"] for r in map(json.loads, sql(
        f"SELECT to_jsonb(c) FROM truth_vault.first_image_candidates('{BANK_V}', '{SINCE}', '{{}}', true, 100) c "
        f"WHERE c.note_id LIKE '{P1}%';").splitlines())], "不在名单里的项目照常出"

    # ── 写结果 + 读的那一面 ──
    sql(f"INSERT INTO truth_vault.note_feature_answers (subject_type, subject_id, question_id, question_version, bank_version, "
        f"bank_sha256, extractor, run_tag, answer) VALUES ('note', '{a}', 'has_specific_time', 1, 'fq-v0.1', 'x', 'llm:m', 'primary', '是');")
    assert write(state(a, "a1", "answered", "final"), COVER_ROWS(a)) == "final"
    v = view(a)
    assert v["status"] == "answered" and v["usable"] is False and v["answers"] is None, "题库镜像那一行不在: 没有一篇能用"
    sync()
    v = view(a)
    assert v["usable"] is True and v["cover_unconfirmed"] is False and v["project_excluded"] is False, v
    assert v["answers"] == {"img_layout": "一张照片"}, f"只出往外给的题里答成了的; 抄下来的字、没验证的题不出: {v['answers']}"
    assert set(v) == {"note_id", "project_id", "status", "usable", "cover_unconfirmed", "project_excluded", "n_files",
                      "bank_version", "model", "checked_at", "answers", "image_changed"}, sorted(v)
    assert v["image_changed"] is False and v["n_files"] == 1
    assert a not in [r["note_id"] for r in cands()], "做过的不再出"

    assert write(state(b, "b1", "answered", "final", n_files=2, col="笔记配图"), COVER_ROWS(b)) == "final"
    v = view(b)
    assert (v["usable"], v["cover_unconfirmed"], v["answers"]) == (False, True, None), f"多图没确认不能用: {v}"
    sync(confirmed=(P1,))
    v = view(b)
    assert (v["usable"], v["cover_unconfirmed"]) == (True, False) and v["answers"] == {"img_layout": "一张照片"}, "确认之后不用重写就放开"
    sync(excluded=(PX, P1))
    assert (view(a)["usable"], view(a)["project_excluded"], view(a)["answers"]) == (False, True, None), "项目先不做 → 不能用"
    sync(surfaced=("img_layout", "img_scene"))
    assert view(a)["answers"] == {"img_layout": "一张照片", "img_scene": "生活场景"}, "往外给的题跟着题库镜像走"
    sql("UPDATE truth_vault.first_image_bank_state SET bank_version = 'fi-v9';")
    assert view(a)["usable"] is False, "题库版本对不上 → 不能用"
    sync()

    # 做完之后运营又加了图 (第一个附件没变 → 不重做、不重问): 多图的规矩在读的那一刻就得跟上, 不能凭做的时候记下的 n_files = 1 放行
    one = {"内容配图": [f("a1")]}
    sql(f"UPDATE truth_vault.notes SET raw_extra = {J({'内容配图': [f('a1'), f('a7'), f('a8'), f('a9')]})} WHERE note_id = '{a}';")
    v = view(a)
    assert (v["n_files"], v["cover_unconfirmed"], v["usable"], v["answers"], v["image_changed"]) == (4, True, False, None, False), \
        f"做完之后又加了图: 多图没确认不能用: {v}"
    assert a not in [r["note_id"] for r in cands()], "第一个附件没变: 不重做 (不为同一张图再花钱)"
    sync(confirmed=(P1,))
    assert (view(a)["usable"], view(a)["n_files"]) == (True, 4), "项目确认之后放开"
    sync()
    # 图片列整个没了: 库里的答案是给一张已经不在的图答的
    sql(f"UPDATE truth_vault.notes SET raw_extra = '{{}}'::jsonb WHERE note_id = '{a}';")
    v = view(a)
    assert (v["image_changed"], v["usable"], v["answers"], v["n_files"]) == (True, False, None, 1), f"图片列没了: 不能用: {v}"
    # 首图换了、还没轮到重做的那一会儿: 旧答案不能当成新图的
    sql(f"UPDATE truth_vault.notes SET raw_extra = {J({'内容配图': [f('a5')]})} WHERE note_id = '{a}';")
    v = view(a)
    assert (v["image_changed"], v["usable"], v["answers"]) == (True, False, None), f"首图换了: 旧答案不能用: {v}"
    sql(f"UPDATE truth_vault.notes SET raw_extra = {J(one)} WHERE note_id = '{a}';")
    assert (view(a)["usable"], view(a)["image_changed"]) == (True, False)

    # 被拒的几种写法
    for bad_state, bad_rows, why in (
            (state(d, "d1", "not_a_cover", "final"), [row(d, "img_kind", "后台或数据截图"), row(d, "img_layout", "一张照片")], "不是封面带了别的题"),
            (state(d, "d1", "not_a_cover", "final"), [row(d, "img_kind", "封面")], "不是封面却写封面"),
            (state(d, "d1", "answered", "final"), [row(d, "img_layout", "一张照片")], "答完了没有 img_kind"),
            (state(d, "d1", "answered", "final"), [row(d, "img_kind", "后台或数据截图")], "答完了 img_kind 不是封面"),
            (state(d, "d1", "answered", "final"), [row(d, "img_kind", "封面", run_tag="primary")], "写到文字题库的 run_tag 下"),
            (state(d, "d1", "answered", "final"), [row(d, "img_kind", "封面"), row(a, "img_layout", "拼图")], "带了别的帖的行"),
            (state(d, "d1", "answered", "final"), [row(d, "img_kind", "封面"), row(d, "title_is_question", "是")], "带了不是首图的题"),
            (state(d, "d1", "download_failed", "counted"), [row(d, "img_kind", "封面")], "没下载到却带答案"),
            (state(d, "d1", "answered", "counted"), [row(d, "img_kind", "封面")], "状态和结局对不上"),
            (state(d, "d1", "answered", "final", project=PX), [row(d, "img_kind", "封面")], "项目对不上"),
            (dict(state(d, "d1", "first_is_video", "final"), source_column="相关截图"), [], "不是那三列")):
        write(bad_state, bad_rows, ok=False)
        assert view(d) == {}, f"{why}: 被拒之后不该留下任何东西"
    assert sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id = '{d}';") == "0"

    # 换了图: 再出来; 重写之后旧答案没了, 文字题库的行还在
    sql(f"UPDATE truth_vault.notes SET raw_extra = {J({'内容配图': [f('a2')]})} WHERE note_id = '{a}';")
    assert cands()[0]["note_id"] == a and cands()[0]["file_sha"] == sha("a2"), "图换了要再出来"
    assert write(state(a, "a2", "not_a_cover", "final"), [row(a, "img_kind", "后台或数据截图")]) == "final"
    assert sql(f"SELECT question_id || ':' || run_tag FROM truth_vault.note_feature_answers WHERE subject_id = '{a}' ORDER BY 1;") \
        == "has_specific_time:primary\nimg_kind:img-primary", "换了图之后旧答案还在 / 或文字题库的行被删了"
    v = view(a)
    assert (v["status"], v["usable"], v["answers"]) == ("not_a_cover", False, None), "模型说不是封面的帖没有能用的特征"
    # 这时候库里: b 答完了 (5 行)、a 不是封面 (1 行), 同一个 run_tag × extractor × 题库版本。自检 #87 不许把 a 数成「半写」
    assert verify_87() == base_87, f"#87 因为首图的行多数了 {verify_87() - base_87} 篇"

    # 整张表刚接进来 / 删了重灌: 所有帖的 ingested_at 都是当天。只看入库时刻的话, 几百篇老帖全算新帖, 一晚 40 张地补 (D-157 不许)
    n_old, n_draft, n_fresh, n_card = [f"{P1}_N{k}" for k in ("old", "draft", "fresh", "card")]
    sql(f"INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('{PN}', 'b', 'p', '保健品');"
        + note(n_old, PN, {"内容配图": [f("n1")]}, new=True, publish="'2026-03-01'")
        + note(n_draft, PN, {"内容配图": [f("n2")]}, new=True)
        + note(n_fresh, PN, {"内容配图": [f("n3")]}, new=True, publish="(now() - interval '2 days')::timestamp")
        + note(n_card, PN, {"内容配图": [f("n4")]}, new=True, card=True, publish="'2026-03-01'"))
    got = {r["note_id"] for r in cands()} & {n_old, n_draft, n_fresh, n_card}
    assert got == {n_fresh, n_card}, f"刚接进来的表: 老帖和没有发布时间的不算新帖, 刚发布的和经验卡的帖照出: {sorted(got)}"
    # 这个项目在库里已经有一周以上的帖之后, 运营新建的行 (还没有发布时间) 才算新帖; 只早三天的不算 (同一次接入分几天灌的)
    sql(note(f"{P1}_Nseed3", PN, {}, new=False, ing="(now() - interval '3 days')::timestamp"))
    assert n_draft not in {r["note_id"] for r in cands()}, "项目里最早的帖只比它早三天: 还当是同一次接入"
    sql(note(f"{P1}_Nseed8", PN, {}, new=False, ing="(now() - interval '8 days')::timestamp"))
    got = {r["note_id"] for r in cands()} & {n_old, n_draft, n_fresh, n_card}
    assert got == {n_draft, n_fresh, n_card}, f"项目已经在库里一周以上: 新建的行算新帖, 老帖还是不算: {sorted(got)}"

    # 重试的梯子
    def st_of(nid):
        return sql(f"SELECT attempts || ',' || tries || ',' || (next_try_at IS NULL) FROM truth_vault.note_first_image WHERE note_id = '{nid}';")
    assert [write(state(d, "d1", "download_failed", "counted", col="笔记配图"), []) for _ in range(3)] == ["retry", "retry", "quarantined"]
    assert st_of(d) == "3,3,true" and d not in [r["note_id"] for r in cands()], "算数的失败满 3 次不再出"
    gaps = sql(f"""SELECT truth_vault.write_first_image_result({J(state(h, 'h1', 'no_answer', 'counted', 3, '图片'))}, '[]');
                   SELECT round(extract(epoch FROM next_try_at - now()) / 3600) FROM truth_vault.note_first_image WHERE note_id = '{h}';
                   SELECT truth_vault.write_first_image_result({J(state(h, 'h1', 'no_answer', 'counted', 3, '图片'))}, '[]');
                   SELECT round(extract(epoch FROM next_try_at - now()) / 3600) FROM truth_vault.note_first_image WHERE note_id = '{h}';""")
    assert gaps.split() == ["retry", "20", "retry", "44"], gaps
    assert h not in [r["note_id"] for r in cands()], "没到重试时间不出"
    sql(f"UPDATE truth_vault.note_first_image SET next_try_at = now() - interval '1 minute' WHERE note_id = '{h}';")
    assert h in [r["note_id"] for r in cands()], "到了重试时间再出"
    sql(f"UPDATE truth_vault.notes SET raw_extra = {J({'图片': [f('h9')]})} WHERE note_id = '{h}';")
    res = [write(state(h, "h9", "model_failed", "infra", col="图片"), []) for _ in range(6)]
    assert res == ["retry"] * 5 + ["quarantined"] and st_of(h) == "0,6,true", f"换了图从头算; 不算数的失败一共试满 6 次也停: {res} {st_of(h)}"

    # 权限
    for role in ("anon", "authenticated"):
        for obj in ("note_first_image", "first_image_bank_state", "v_first_image_features", "v_note_first_image_source"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert sql(f"SELECT has_table_privilege('{role}', 'truth_vault.{obj}', '{priv}');") == "f", (role, obj, priv)
        for fn in ("first_image_candidates(TEXT,TIMESTAMP,TEXT[],BOOLEAN,INT)", "write_first_image_result(JSONB,JSONB)",
                   "sync_first_image_bank(TEXT,TEXT,TEXT[],TEXT[],TEXT[])"):
            assert sql(f"SELECT has_function_privilege('{role}', 'truth_vault.{fn}', 'EXECUTE');") == "f", (role, fn)
    assert sql("SELECT relrowsecurity FROM pg_class WHERE oid = 'truth_vault.note_first_image'::regclass;") == "t"
    assert sql("SELECT relrowsecurity FROM pg_class WHERE oid = 'truth_vault.first_image_bank_state'::regclass;") == "t"
    assert sql("SELECT has_table_privilege('service_role', 'truth_vault.v_first_image_features', 'SELECT') AND "
               "has_function_privilege('service_role', 'truth_vault.write_first_image_result(JSONB,JSONB)', 'EXECUTE');") == "t"

    # 帖子删了, 状态行跟着走
    sql(f"DELETE FROM truth_vault.notes WHERE note_id = '{b}';")
    assert view(b) == {}
    print("  A 取列 / 该做哪些 / 写结果的规矩 / 重试 / 读的那一面 / 权限 ✓")


class PsqlStore:
    """和 first_image_pass.SupabaseStore 调的是同三个函数, 只是走 psql。"""

    def sync_bank(self, bank):
        sql(f"SELECT truth_vault.sync_first_image_bank('{bank['bank_version']}', '{bank['_sha256']}', "
            f"{arr(bank['cover_confirmed_projects'])}, {arr(bank['excluded_projects'])}, {arr(bank['surfaced_questions'])});")

    def candidates(self, bank, cards_only, limit):
        import first_image_pass as P
        out = sql(f"SELECT to_jsonb(c) FROM truth_vault.first_image_candidates('{bank['bank_version']}', '{P.NEW_SINCE}', "
                  f"{arr(bank['excluded_projects'])}, {'true' if cards_only else 'false'}, {int(limit)}) c "
                  f"WHERE c.note_id LIKE '{P1}%' OR c.note_id LIKE '{PX}%';")
        return [json.loads(line) for line in out.splitlines() if line]

    def write(self, st, rows):
        return sql(f"SELECT truth_vault.write_first_image_result({J(st)}, {J(rows)});")


def part_b() -> None:
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent))
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("::warning::check_first_image_pg: 这个环境没有 pyyaml, B 段「first_image_pass 在真库上跑一趟」没跑 (A 段照常)")
        return
    import base64
    import contextlib
    import copy
    import io
    import re

    try:
        import first_image as FI
        import first_image_pass as P
    except ImportError as exc:
        print(f"::warning::check_first_image_pg: 这个环境缺 {exc.name}, B 段「first_image_pass 在真库上跑一趟」没跑 (A 段照常)")
        return

    cleanup()
    bank = copy.deepcopy(P.load_bank())
    bank["excluded_projects"] = [PX]
    import feishu_media as FM
    ids = {k: f"{P1}_{k}" for k in ("card", "multi", "notcover", "video", "old", "contra", "tcard", "saidnone")}
    ids["deny"] = f"{P1}_aaa"                  # 经验卡的帖, 排在所有帖前面; 飞书对它这一个文件回 403
    sql(f"INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('{P1}', 'b', 'p', '保健品'), ('{PX}', 'b', 'p', '保健品');"
        + note(ids["card"], P1, {"内容配图": [f("card")]}, new=False, card=True)
        + note(ids["deny"], P1, {"内容配图": [f("DENY")]}, new=False, card=True)
        + note(ids["multi"], P1, {"笔记配图": [f("multi"), f("multi2")]}, new=True)
        + note(ids["notcover"], P1, {"图片": [f("NOTCOVER")]}, new=True)
        + note(ids["video"], P1, {"内容配图": [f("video", typ="video/mp4")]}, new=True)
        + note(ids["old"], P1, {"内容配图": [f("old")]}, new=False)
        + note(ids["contra"], P1, {"内容配图": [f("CONTRA")]}, new=True)
        + note(ids["tcard"], P1, {"内容配图": [f("TCARD")]}, new=True)
        + note(ids["saidnone"], P1, {"内容配图": [f("SAIDNONE")]}, new=True)
        + note(f"{PX}_x", PX, {"内容配图": [f("x")]}, new=True, card=True))
    asks: list[str] = []
    downloads: list[str] = []

    def download(file):
        downloads.append(file["file_token"])
        if "DENY" in file["file_token"]:
            raise FM.MediaError(FM.NO_PERMISSION, "http403")
        return file["file_token"].encode()

    def shrink(data, sides, decode="auto"):
        return {"pixels": 1_000_000, "images": {s: (data, 768, 1024) for s in sides}}

    def ask(model, prompt, block):
        key = base64.b64decode(block[1]).decode()
        asks.append(key)
        idx = FI.question_index(bank)
        ans = []
        for qid in re.findall(r"id: (img_[a-z_]+)", prompt):
            if qid == "img_kind":
                v = "后台或数据截图" if "NOTCOVER" in key else "封面"
            elif qid == "img_main_text":
                v = "" if "TCARD" in key else ("没有" if "SAIDNONE" in key else "合成的大字 3 天")
            elif qid == "img_text_amount":
                v = "没有字" if "CONTRA" in key or "SAIDNONE" in key else "一句大字"
            elif qid == "img_layout" and "TCARD" in key:
                v = "纯文字卡片"
            elif qid == "img_text_kind":
                v = "结果或结论"
            else:
                v = FI.option_values(idx[qid])[0]
            ans.append({"id": qid, "answer": v})
        return json.dumps({"answers": ans}, ensure_ascii=False), {"input": 1500, "output": 60}

    def go():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return P.run_pass(bank=bank, store=PsqlStore(), mode="nightly", download=download, shrinker=shrink, ask=ask)

    res = go()
    assert res["ended"] == "done" and res["candidates"] == 8, res
    assert res["status"] == {"answered": 4, "not_a_cover": 1, "first_is_video": 1, "download_failed": 1, "no_answer": 1}, res["status"]
    # fi-v0.3: CONTRA 「字是哪一种」答的是「结果或结论」, 第四条 (text_kind_without_text) 也中 (作废的题、原因和第一条一样)
    assert res["partial_void"] == {"no_text_but_transcribed:transcribed_text": 1, "text_but_not_transcribed:empty_text": 1,
                                   "text_kind_without_text": 1} \
        and res["no_answer_why"] == {"round:no_text_but_transcribed:said_none_in_words": 1}, res
    assert downloads[0] == tok("DENY"), "夹具: 被拒的那一篇要排第一"
    tries = lambda: sql(f"SELECT attempts || ',' || tries || ',' || (next_try_at IS NOT NULL) FROM truth_vault.note_first_image "  # noqa: E731
                        f"WHERE note_id = '{ids['deny']}';")
    assert tries() == "0,1,true", f"排第一的帖被拒: 要记一笔 (不算数), 不然它每晚都排第一: {tries()}"
    assert len(asks) == 7 + 7 + 7 + 7 + 7 + 1 and tok("old") not in downloads and tok("x") not in downloads and tok("video") not in downloads
    v = view(ids["card"])
    assert v["usable"] is True and v["model"] == P.cheap_model() and set(v["answers"]) == set(P.surfaced_questions(bank)), v
    # fi-v0.3: img_text_has_number 是 reworded_unverified, 不往外给 —— 视图里没有这个键; 库里那一行照存, 去 note_feature_answers 读
    assert "img_text_has_number" not in v["answers"] and "img_text_kind" not in v["answers"] and "img_main_text" not in v["answers"], v
    assert sql("SELECT answer FROM truth_vault.note_feature_answers "
               f"WHERE subject_id = '{ids['card']}' AND run_tag = 'img-primary' AND question_id = 'img_text_has_number';") == "有"
    assert (view(ids["multi"])["usable"], view(ids["multi"])["cover_unconfirmed"], view(ids["multi"])["answers"]) == (False, True, None)
    assert (view(ids["notcover"])["status"], view(ids["notcover"])["answers"]) == ("not_a_cover", None)
    assert view(ids["video"])["status"] == "first_is_video" and view(ids["video"])["model"] is None
    assert view(ids["old"]) == {} and view(f"{PX}_x") == {}, "老帖和先不做的项目没有行"
    n_rows = sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id LIKE '{P1}%' AND run_tag = 'img-primary';")
    assert n_rows == str(13 + 13 + 13 + 13 + 1), n_rows
    # 自相矛盾只作废有关的题 (D-160): 库收下 inconsistent:* 的行; 这一篇能用, answers 里没有字那两道题, 别的照有
    void = sql("SELECT string_agg(question_id || '=' || invalid_reason, ',' ORDER BY question_id) FROM truth_vault.note_feature_answers "
               f"WHERE subject_id = '{ids['contra']}' AND run_tag = 'img-primary' AND answer IS NULL;")
    assert void == ("img_main_text=inconsistent:no_text_but_transcribed,img_text_amount=inconsistent:no_text_but_transcribed,"
                    "img_text_has_number=source_invalid,img_text_kind=inconsistent:no_text_but_transcribed,"
                    "img_text_matches_title=source_invalid"), void
    assert sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id = '{ids['contra']}' AND run_tag = 'img-primary';") == "13"
    v = view(ids["contra"])
    assert (v["status"], v["usable"]) == ("answered", True), v
    assert set(v["answers"]) == set(P.surfaced_questions(bank)) - {"img_text_kind", "img_text_has_number"} and len(v["answers"]) == 5, \
        f"没有键 = 这道题没答成; 别的往外给的题照有: {v['answers']}"
    assert sql(f"SELECT next_try_at IS NULL FROM truth_vault.note_first_image WHERE note_id = '{ids['contra']}';") == "t", "定了, 不重试"
    # 说了有字、大字是空的、版式是纯文字卡片 (第二条): 版式也作废 —— 纯文字卡片说的就是有字, 留着它等于信了一边
    v = view(ids["tcard"])
    assert (v["status"], v["usable"]) == ("answered", True) and set(v["answers"]) == set(P.surfaced_questions(bank)) - {
        "img_text_kind", "img_text_has_number", "img_layout"}, v
    assert sql("SELECT invalid_reason FROM truth_vault.note_feature_answers "
               f"WHERE subject_id = '{ids['tcard']}' AND run_tag = 'img-primary' AND question_id = 'img_layout';") \
        == "inconsistent:text_but_not_transcribed"
    # 说了没有字、抄出来的是「没有」(两次说的是一回事): 照旧 no_answer, 一行答案都不写, 算一次、过一天重问
    v = view(ids["saidnone"])
    assert (v["status"], v["usable"], v["answers"]) == ("no_answer", False, None), v
    assert sql(f"SELECT attempts || ',' || tries || ',' || (next_try_at IS NOT NULL) FROM truth_vault.note_first_image "
               f"WHERE note_id = '{ids['saidnone']}';") == "1,1,true"
    assert sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id = '{ids['saidnone']}';") == "0"
    assert sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id LIKE '{P1}%' AND run_tag = 'primary';") == "0"
    stored = sql("SELECT string_agg(file_sha, ',') FROM truth_vault.note_first_image;")
    assert "boxcn" not in stored and sql(f"SELECT count(*) FROM truth_vault.note_first_image WHERE file_sha = '{sha('card')}';") == "1"

    before = len(asks)
    res = go()
    assert res["candidates"] == 0 and len(asks) == before and res["status"] == {}, "第二趟: 不重复做、不重复问"
    # 到了重试时间: 被拒的那一篇再试一次 (还是被拒, 再记一笔), 同一晚新来的帖照做 —— 它卡不住别的帖
    sql(f"UPDATE truth_vault.note_first_image SET next_try_at = now() - interval '1 minute' WHERE note_id = '{ids['deny']}';"
        + note(f"{P1}_late", P1, {"内容配图": [f("late")]}, new=True))
    res = go()
    assert res["ended"] == "done" and res["status"] == {"download_failed": 1, "answered": 1}, res
    assert tries() == "0,2,true" and view(f"{P1}_late")["usable"] is True
    before = len(asks)
    # 有人确认了这张表: 改题库名单, 下一趟只同步名单, 多图的帖就放开, 一次模型都不问
    bank["cover_confirmed_projects"] = [P1]
    res = go()
    assert len(asks) == before and view(ids["multi"])["usable"] is True and view(ids["multi"])["answers"], "确认之后不用重问"
    print("  B first_image_pass 在真库上跑一趟: 状态、答案、读的那一面都对; 第二趟零调用; 确认项目之后不重问 ✓")


def main() -> int:
    if os.environ.get("PGHOST", "") not in ("", "localhost", "127.0.0.1") or \
            os.environ.get("PGDATABASE") not in ("tv_ci", "tv_repair", "tv_full_ci"):
        raise SystemExit("这个夹具只在一次性的本地库上跑 (tv_ci / tv_repair / tv_full_ci)")
    cleanup()
    try:
        part_a()
        part_b()
    finally:
        cleanup()
    print("check_first_image_pg: 过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
