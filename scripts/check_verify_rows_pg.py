#!/usr/bin/env python3
"""本批 verify 行和 AU-F02b ④ 两份 owner SQL 在真 Postgres 上的夹具与反证 (ci.yml sql job 的最后一步调;
v1_29 和 Step 0b 的看板 / 安全文件都跑过之后)。

只在一次性的本地库上跑; 走 psql, 只用标准库。夹具都带 CI_B1 前缀或 _1199_ 这种不会撞上生产的名字, 最后删干净。

  §0 整份 scripts/verify_supabase_state.sql 在 PG 16 上跑得通 (语法错一处整份都不出数)
  §1 #92 没登记的备份: 合成一张 autowriter._bak_1199_* → 1; 登记过的名字 (D-129 那种) 和 backup_d129_ids 不算; 删掉 → 0
  §2 #92b: 给这张备份表 GRANT SELECT TO anon → 1、改给 authenticated → 1; 收回 → 0
  §3 #105 v_dash_* 视图个数 = 18, 多建一个 → 19; #106 给 anon 一条 INSERT → 1; #107 关掉一张三省六部表的 RLS → 1
  §4 #108 input_sha: 没有这一列 → N/A; 第一条带 input_sha 的分之前的空行不算、之后的空行算
  §5 #109 / #110 + 两份 AU-F02b ④ owner SQL: 改指过的笔记上旧帖的运营评论数出 2、旧样本数出 1; 旧评论还在时 withdraw 拒跑;
     先模拟最坏的默认授权 (truth_vault 新表默认给 anon / authenticated), 再跑
     cleanup_repointed_stale_comments_au_f02b.sql、withdraw_repointed_stale_ssll_samples_au_f02b.sql 各两遍 →
     只删 / 只撤该删的 (同篇的新评论、读者评论、改指之后的评论、没改指的篇、只换了短链接的篇、链接只差空白的篇、
     没有原文键也没换发布时间的篇、改指之后才推的样本都不动), 判分行跟着删,
     备份表有那几行、anon / authenticated 一样权限都没有; 再照表注释里的回滚语句跑一遍 → 全回来
  §6 改指的认法 (rp 那一段) 在 #109、#110、两份 owner SQL 里 7 处一字不差; 「第 ③ 条」在 4 处都有
  §7 批 3 的 #111 / #112 (v1_34、v1_35 在这一步之前跑过): 底数都是 0 (不是 N/A —— 查询写坏了 safe_count 回 NULL 显示 N/A,
     和「迁移还没跑」长得一样, 所以底数必须是 0); #111 把书架视图换成一张有空 rank_score、先验越界的假视图 → 2,
     没有 account_prior 列 → N/A; #112 给 anon → 1、anon + authenticated → 2 (都在事务里, 回滚)
反证 (改坏之后必须红):
  · #92 的 VALUES 删掉 D-129 那一条 → §1「登记过的名字不算」红
  · #92b 只留 anon → §2 authenticated 那一步红
  · #109 / cleanup 的规则去掉 c.created_at < rp.last_rp → 改指之后的评论被删, §5 红
  · #110 / withdraw 的规则去掉 r.created_at < last_rp → 改指之后才推的样本被数 / 被撤, §5 红
  · cleanup 的规则去掉 changed_cols ? 'account_id' → 只换短链接的篇也被删, §5 红
  · 任一处去掉 btrim → 链接只差空白的篇也算改指, §5 或 §6 红
  · 去掉第 ③ 条 (原文键 / 发布时间) → 没原文键、没换发布时间的篇的评论被删, §5 红
  · withdraw 去掉 post_body IS DISTINCT FROM → (本夹具里正文一样的样本) 被撤, §5 红
  · 两份 owner SQL 去掉 REVOKE → 默认授权让 anon / authenticated 拿到备份表, §5 红
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PSQL = ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
SEP = "\x1f"
P = "CI_B1RP"
# 夹具模拟最坏的情况: truth_vault 下新建的表默认就给 anon / authenticated (生产没有; 这样两份 owner SQL 的 REVOKE 才真被考到)
DEFAULT_GRANT = "ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault GRANT SELECT, INSERT ON TABLES TO anon, authenticated;"
UNDO_DEFAULT_GRANT = "ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault REVOKE SELECT, INSERT ON TABLES FROM anon, authenticated;"


def sql(text: str) -> str:
    res = subprocess.run(PSQL, input=text, text=True, capture_output=True, timeout=120)
    if res.returncode:
        raise SystemExit(f"psql 失败:\n{res.stderr[-2000:]}\n--- 输入开头:\n{text[:400]}")
    return res.stdout.strip()


def run_file(path: Path) -> str:
    res = subprocess.run(PSQL + ["-f", str(path)], text=True, capture_output=True, timeout=120)
    if res.returncode:
        raise SystemExit(f"psql -f {path.name} 失败:\n{res.stderr[-2000:]}")
    return res.stdout.strip()


def verify(prefix: str = "", suffix: str = "") -> dict[str, tuple[str, str]]:
    """跑整份 verify, 回 {编号: (actual, expected)}。prefix / suffix 用来包一层事务。"""
    text = prefix + (HERE / "verify_supabase_state.sql").read_text(encoding="utf-8") + suffix
    res = subprocess.run(PSQL + ["-F", SEP], input=text, text=True, capture_output=True, timeout=120)
    if res.returncode:
        raise SystemExit(f"§0 verify_supabase_state.sql 在 PG 上跑不通:\n{res.stderr[-2000:]}")
    out = {}
    for ln in res.stdout.splitlines():
        parts = ln.split(SEP)
        if len(parts) >= 7 and re.fullmatch(r"\d+[a-z]?", parts[0]):
            out[parts[0]] = (parts[3], parts[4])
    if len(out) < 60:
        raise SystemExit(f"§0 verify 只出了 {len(out)} 行, 解析不对或文件坏了")
    return out


def want(got: dict, ord_: str, value: str, why: str) -> None:
    if got[ord_][0] != value:
        raise SystemExit(f"❌ #{ord_} 应为 {value}, 实际 {got[ord_][0]} —— {why}")


def main() -> int:
    db = os.environ.get("PGDATABASE", "")
    if not (db.startswith("tv_ci") or db in ("tv_repair", "tv_full_ci")):
        raise SystemExit("这个夹具只在一次性的本地库上跑 (tv_ci 之类)")

    # 上一次跑到一半红了留下的夹具先清掉 (这一步本身可重跑)
    sql(f"""DROP TABLE IF EXISTS autowriter._bak_1199_ci_unregistered, truth_vault.backup_notes_d129_20261026;
        DROP VIEW IF EXISTS public.v_dash_ci_probe;
        REVOKE INSERT ON public.v_dash_overview FROM anon;
        ALTER TABLE public.stage_logs ENABLE ROW LEVEL SECURITY;
        DELETE FROM truth_vault.content_scores WHERE subject_id LIKE 'CI_B1%';
        UPDATE truth_vault.notes SET synced_to_ssll_at = NULL, synced_ssll_reference_sample_id = NULL WHERE note_id LIKE '{P}%';
        DELETE FROM public.reference_samples WHERE source_truth_vault_note_id LIKE '{P}%';
        DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE '{P}%';
        DELETE FROM truth_vault.comments WHERE note_id LIKE '{P}%';
        DELETE FROM truth_vault.notes WHERE note_id LIKE '{P}%';
        DELETE FROM truth_vault.projects WHERE project_id = '{P}';
        DELETE FROM truth_vault.audit_log WHERE row_id LIKE '{P}%';
        DROP TABLE IF EXISTS truth_vault.backup_repoint_stale_comments_20261125, truth_vault.backup_repoint_stale_comment_judge_20261125,
                             truth_vault.backup_repoint_stale_ssll_samples_20261125, truth_vault.backup_repoint_stale_ssll_marks_20261125;
        {UNDO_DEFAULT_GRANT}""")

    # §0 + 底数
    base = verify()
    for o, v in (("92", "0"), ("92b", "0"), ("105", "18"), ("106", "0"), ("107", "0"), ("108", "0"),
                 ("109", "0"), ("110", "0"), ("111", "0"), ("112", "0")):
        want(base, o, v, "CI 库上跑完所有迁移之后的底数 (批 2 的三张备份表这时还在, 名字要登记、anon / authenticated 碰不到)")
    print("  §0 整份 verify 跑得通; 本批新行底数都对 ✓")

    # §1 / §2 备份登记
    sql("""CREATE TABLE autowriter._bak_1199_ci_unregistered (id int);
           CREATE TABLE truth_vault.backup_notes_d129_20261026 (id int);
           CREATE TABLE IF NOT EXISTS truth_vault.backup_d129_ids_20261026 (old_id text, new_id text);""")
    got = verify()
    want(got, "92", "1", "只有合成的 _bak_1199_ 那张没登记; D-129 那种登记过的名字和 backup_d129_ids 不算")
    want(got, "92b", "0", "没给 anon 授权")
    sql("GRANT SELECT ON autowriter._bak_1199_ci_unregistered TO anon;")
    want(verify(), "92b", "1", "anon 能读这张备份表")
    sql("REVOKE ALL ON autowriter._bak_1199_ci_unregistered FROM anon;"
        " GRANT SELECT ON autowriter._bak_1199_ci_unregistered TO authenticated;")
    want(verify(), "92b", "1", "authenticated 能读这张备份表")
    sql("""REVOKE ALL ON autowriter._bak_1199_ci_unregistered FROM anon, authenticated;
           DROP TABLE autowriter._bak_1199_ci_unregistered; DROP TABLE truth_vault.backup_notes_d129_20261026;""")
    got = verify()
    want(got, "92", "0", "合成表删掉之后")
    want(got, "92b", "0", "合成表删掉之后")
    print("  §1 §2 #92 只数没登记的 (登记过的、d129 映射表不算) · #92b 数 anon / authenticated 能碰的 ✓")

    # §3 看板与权限
    sql("CREATE VIEW public.v_dash_ci_probe AS SELECT 1 AS x; GRANT INSERT ON public.v_dash_overview TO anon;"
        " ALTER TABLE public.stage_logs DISABLE ROW LEVEL SECURITY;")
    got = verify()
    want(got, "105", "19", "多建了一个 v_dash_*")
    want(got, "106", "1", "anon 有一条 INSERT")
    want(got, "107", "1", "stage_logs 关了 RLS")
    sql("DROP VIEW public.v_dash_ci_probe; REVOKE INSERT ON public.v_dash_overview FROM anon;"
        " ALTER TABLE public.stage_logs ENABLE ROW LEVEL SECURITY;")
    got = verify()
    for o, v in (("105", "18"), ("106", "0"), ("107", "0")):
        want(got, o, v, "探针撤掉之后")
    print("  §3 #105 视图个数 · #106 anon 写权限 · #107 三省六部表 RLS ✓")

    # §4 #108 input_sha
    na = verify("BEGIN;\nALTER TABLE truth_vault.content_scores DROP COLUMN input_sha;\n", "\nROLLBACK;\n")
    want(na, "108", "N/A", "没有 input_sha 这一列 (v1_29 没跑)")
    sql("""DELETE FROM truth_vault.content_scores WHERE subject_id LIKE 'CI_B1%';
        INSERT INTO truth_vault.content_scores (subject_type, subject_id, project_id, scorer_version, score, pct_in_project,
                                                cutpoints, scored_at, input_sha) VALUES
          ('note', 'CI_B1_s0', 'CI_B1', 'ci', 0.5, 0.5, 'pooled', '2026-11-01 00:00+00', NULL),
          ('note', 'CI_B1_s1', 'CI_B1', 'ci', 0.5, 0.5, 'pooled', '2026-11-02 00:00+00', 'sha-1'),
          ('note', 'CI_B1_s2', 'CI_B1', 'ci', 0.5, 0.5, 'pooled', '2026-11-03 00:00+00', NULL);""")
    want(verify(), "108", "1", "第一条带 input_sha 之前的空行不算, 之后的算")
    sql("DELETE FROM truth_vault.content_scores WHERE subject_id LIKE 'CI_B1%';")
    want(verify(), "108", "0", "夹具删掉之后")
    print("  §4 #108: 没列 → N/A · 只数第一条带 sha 之后的空行 ✓")

    # §5 改指过的笔记 + 两份 owner SQL
    try:
        s5_repoint()
    finally:
        sql(UNDO_DEFAULT_GRANT)
    # §6 规则文本一致
    s6_rule_text()
    # §7 批 3 的 #111 / #112
    s7_batch3_rows()
    print("✅ check_verify_rows_pg: §0–§7 全过")
    return 0


def _cleanup_fixture() -> None:
    sql(f"""
    UPDATE truth_vault.notes SET synced_to_ssll_at = NULL, synced_ssll_reference_sample_id = NULL WHERE note_id LIKE '{P}%';
    DELETE FROM public.reference_samples WHERE source_truth_vault_note_id LIKE '{P}%';
    DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE '{P}%';
    DELETE FROM truth_vault.comments WHERE note_id LIKE '{P}%';
    DELETE FROM truth_vault.notes WHERE note_id LIKE '{P}%';
    DELETE FROM truth_vault.projects WHERE project_id = '{P}';
    DELETE FROM truth_vault.audit_log WHERE row_id LIKE '{P}%';
    DROP TABLE IF EXISTS truth_vault.backup_repoint_stale_comments_20261125, truth_vault.backup_repoint_stale_comment_judge_20261125,
                         truth_vault.backup_repoint_stale_ssll_samples_20261125, truth_vault.backup_repoint_stale_ssll_marks_20261125;
    """)


BACKUPS = ("backup_repoint_stale_comments_20261125", "backup_repoint_stale_comment_judge_20261125",
           "backup_repoint_stale_ssll_samples_20261125", "backup_repoint_stale_ssll_marks_20261125")


def s5_repoint() -> None:
    _cleanup_fixture()
    # 笔记 (都在合成项目里; 账号有外键, 夹具不设; audit 行是手写的, 改指在 11-10):
    #   甲 a: 改指, 有原文键。旧评论 a_old 删; a_new 在原文里、a_late 改指之后入库、a_rd 读者评论, 都留。改指前推的旧样本撤。
    #   乙 b: 只换了短链接 (没换账号), 不是改指。b_x 原文里没有, 留; 旧样本留。
    #   丙 c: 改指, 样本改指前推的但正文和现在一样, 留。
    #   丁 d: 改指, 样本改指之后才推、正文后来又改过 (和现在不一样), 留 (守 r.created_at < last_rp)。
    #   戊 e: 链接只差首尾空白 + 换了账号, 不算改指。e_x 原文里没有, 留; 旧样本留 (守 btrim)。
    #   己 f: 改指, 没有原文键, 改指时发布时间也没换。f_old 留 (第 ③ 条; 「找不到」只说明源清空了)。
    #   庚 g: 改指且换了发布时间, 没有原文键。g_old 删 (第 ③ 条的另一半)。
    sql(f"""
    INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('{P}', 'b', 'p', '保健品');
    INSERT INTO truth_vault.notes (note_id, project_id, raw_content, raw_extra, publish_url) VALUES
      ('{P}_a', '{P}', '新帖正文', '{{"_comment_text": "1. 新帖评论甲\\n2. 新帖评论乙"}}', 'u-new'),
      ('{P}_b', '{P}', '乙篇正文', '{{"_comment_text": "1. 乙篇评论"}}', 'u-b2'),
      ('{P}_c', '{P}', '丙篇正文', '{{"_comment_text": "1. 丙篇新评论"}}', 'u-c2'),
      ('{P}_d', '{P}', '丁篇正文改过', '{{"_comment_text": "1. 丁篇评论"}}', 'u-d2'),
      ('{P}_e', '{P}', '戊篇正文', '{{"_comment_text": "1. 戊篇评论"}}', 'u-e'),
      ('{P}_f', '{P}', '己篇正文', '{{}}', 'u-f2'),
      ('{P}_g', '{P}', '庚篇正文', '{{}}', 'u-g2');
    INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at) VALUES
      ('truth_vault', 'notes', '{P}_a', 'UPDATE', '{{"publish_url": ["u-old", "u-new"], "account_id": ["acc-old", "acc-new"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_b', 'UPDATE', '{{"publish_url": ["u-b1", "u-b2"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_c', 'UPDATE', '{{"publish_url": ["u-c1", "u-c2"], "account_id": ["acc-c1", "acc-c2"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_d', 'UPDATE', '{{"publish_url": ["u-d1", "u-d2"], "account_id": ["acc-d1", "acc-d2"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_e', 'UPDATE', '{{"publish_url": [" u-e\\t", "u-e"], "account_id": ["acc-e1", "acc-e2"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_f', 'UPDATE', '{{"publish_url": ["u-f1", "u-f2"], "account_id": ["acc-f1", "acc-f2"]}}', '2026-11-10 00:00'),
      ('truth_vault', 'notes', '{P}_g', 'UPDATE', '{{"publish_url": ["u-g1", "u-g2"], "account_id": ["acc-g1", "acc-g2"],
                                                      "publish_time": ["2026-08-01", "2026-08-05"]}}', '2026-11-10 00:00');
    INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, comment_role, created_at, source) VALUES
      ('{P}_a_old',   '{P}_a', '{P}', '旧帖评论',     '素人', '2026-11-01 00:00', NULL),
      ('{P}_a_new',   '{P}_a', '{P}', '新帖评论甲',   '素人', '2026-11-01 00:00', NULL),
      ('{P}_a_late',  '{P}_a', '{P}', '改指之后的',   '素人', '2026-11-11 00:00', NULL),
      ('{P}_a_rd',    '{P}_a', '{P}', '读者评论',     '路人', '2026-11-01 00:00', 'linkcheck_digest'),
      ('{P}_b_x',     '{P}_b', '{P}', '原文里没有',   '素人', '2026-11-01 00:00', NULL),
      ('{P}_e_x',     '{P}_e', '{P}', '原文里没有',   '素人', '2026-11-01 00:00', NULL),
      ('{P}_f_old',   '{P}_f', '{P}', '源清空了',     '素人', '2026-11-01 00:00', NULL),
      ('{P}_g_old',   '{P}_g', '{P}', '庚篇旧评论',   '素人', '2026-11-01 00:00', NULL);
    INSERT INTO truth_vault.note_feature_answers (subject_type, subject_id, question_id, question_version, bank_version, bank_sha256,
                                                  extractor, run_tag, answer) VALUES
      ('comment', '{P}_a_old', 'q1', 1, 'ci', 'ci', 'jev:ci', 'primary', '是'),
      ('comment', '{P}_a_old', 'q2', 1, 'ci', 'ci', 'jev:ci', 'primary', '否'),
      ('comment', '{P}_a_new', 'q1', 1, 'ci', 'ci', 'jev:ci', 'primary', '是'),
      ('comment', '{P}_f_old', 'q1', 1, 'ci', 'ci', 'jev:ci', 'primary', '是'),
      ('comment', '{P}_g_old', 'q1', 1, 'ci', 'ci', 'jev:ci', 'primary', '否');
    INSERT INTO public.reference_samples (title, post_body, source_truth_vault_note_id, created_at) VALUES
      ('ci', '旧帖正文', '{P}_a', '2026-11-01 00:00+00'),
      ('ci', '乙篇旧正文', '{P}_b', '2026-11-01 00:00+00'),
      ('ci', '丙篇正文', '{P}_c', '2026-11-01 00:00+00'),
      ('ci', '丁篇正文', '{P}_d', '2026-11-12 00:00+00'),
      ('ci', '戊篇旧正文', '{P}_e', '2026-11-01 00:00+00');
    UPDATE truth_vault.notes n SET synced_to_ssll_at = '2026-11-01 00:00', synced_ssll_reference_sample_id = r.id
      FROM public.reference_samples r WHERE r.source_truth_vault_note_id = n.note_id AND n.note_id LIKE '{P}%';
    DELETE FROM truth_vault.audit_log WHERE row_id LIKE '{P}%' AND occurred_at > '2026-11-20';
    """)
    got = verify()
    want(got, "109", "2", "甲篇的 a_old 和庚篇的 g_old (乙没改指、戊链接只差空白、己没原文键也没换发布时间、a_late 是改指之后的)")
    want(got, "110", "1", "只有甲篇的样本 (乙没改指、丙正文一样、丁改指之后才推、戊链接只差空白)")

    # withdraw 在旧帖评论还在时必须拒跑、什么都不改 (重推会把旧热评带出去)
    res = subprocess.run(PSQL + ["-f", str(HERE / "withdraw_repointed_stale_ssll_samples_au_f02b.sql")],
                         text=True, capture_output=True, timeout=120)
    if res.returncode == 0 or "cleanup_repointed_stale_comments_au_f02b.sql" not in res.stderr:
        raise SystemExit("❌ §5 旧帖评论还在时, withdraw 应拒跑并点名先跑 cleanup")
    want(verify(), "110", "1", "withdraw 拒跑之后样本一个没动")

    sql(DEFAULT_GRANT)
    for _ in range(2):
        run_file(HERE / "cleanup_repointed_stale_comments_au_f02b.sql")
        run_file(HERE / "withdraw_repointed_stale_ssll_samples_au_f02b.sql")
    sql(UNDO_DEFAULT_GRANT)
    got = verify()
    want(got, "109", "0", "跑过 cleanup 之后")
    want(got, "110", "0", "跑过 withdraw 之后")
    left = sql(f"SELECT string_agg(comment_id, ',' ORDER BY comment_id) FROM truth_vault.comments WHERE note_id LIKE '{P}%'")
    expect = ",".join(sorted(f"{P}_{x}" for x in ("a_new", "a_late", "a_rd", "b_x", "e_x", "f_old")))
    if left != expect:
        raise SystemExit(f"❌ §5 cleanup 删多了或删少了: 剩 {left}, 应剩 {expect}")
    judge = sql(f"SELECT string_agg(subject_id || '/' || question_id, ',' ORDER BY subject_id, question_id) FROM truth_vault.note_feature_answers "
                f"WHERE subject_id LIKE '{P}%'")
    if judge != f"{P}_a_new/q1,{P}_f_old/q1":
        raise SystemExit(f"❌ §5 判分行应只剩 a_new、f_old 各一行, 实际 {judge}")
    samples = sql(f"SELECT string_agg(source_truth_vault_note_id, ',' ORDER BY source_truth_vault_note_id) FROM public.reference_samples "
                  f"WHERE source_truth_vault_note_id LIKE '{P}%'")
    if samples != f"{P}_b,{P}_c,{P}_d,{P}_e":
        raise SystemExit(f"❌ §5 withdraw 应只撤甲篇的样本, 剩 {samples}")
    marks = sql(f"SELECT string_agg(note_id || ':' || (synced_to_ssll_at IS NULL)::text, ',' ORDER BY note_id) FROM truth_vault.notes "
                f"WHERE note_id LIKE '{P}%' AND note_id < '{P}_f'")
    if marks != f"{P}_a:true,{P}_b:false,{P}_c:false,{P}_d:false,{P}_e:false":
        raise SystemExit(f"❌ §5 只该清甲篇的通道 1 标记: {marks}")
    counts = sql("SELECT " + " || ',' || ".join(f"(SELECT count(*) FROM truth_vault.{t})" for t in BACKUPS) + ";")
    if counts != "2,3,1,1":
        raise SystemExit(f"❌ §5 备份表行数 (评论, 判分, 样本, 标记) 应为 2,3,1,1 (跑两遍不多行), 实际 {counts}")
    leak = sql("SELECT coalesce(string_agg(r.role || ':' || c.relname, ','), '') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
               "CROSS JOIN (VALUES ('anon'), ('authenticated')) r(role) "
               "WHERE n.nspname = 'truth_vault' AND c.relname LIKE 'backup_repoint_stale_%' "
               "AND has_table_privilege(r.role, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')")
    if leak:
        raise SystemExit(f"❌ §5 默认授权下, 备份表还有客户端角色的权限 (REVOKE 没起作用): {leak}")
    got = verify()
    want(got, "92", "0", "四张新备份表都已登记")
    want(got, "92b", "0", "四张新备份表 anon / authenticated 都碰不到")

    # 照表注释里的回滚语句跑
    for tbl in BACKUPS:
        cmt = sql(f"SELECT obj_description('truth_vault.{tbl}'::regclass, 'pg_class')")
        m = re.search(r"((?:INSERT INTO|UPDATE) .*?;)", cmt)
        if not m:
            raise SystemExit(f"❌ §5 {tbl} 的注释里没有回滚语句")
        sql(m.group(1))
    got = verify()
    want(got, "109", "2", "照注释回滚之后旧评论回来了")
    want(got, "110", "1", "照注释回滚之后旧样本和标记回来了")
    if sql(f"SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id IN ('{P}_a_old', '{P}_g_old')") != "3":
        raise SystemExit("❌ §5 回滚之后判分行没回来")

    _cleanup_fixture()
    print("  §5 #109 / #110 和两份 AU-F02b ④ owner SQL: 只删旧帖评论和判分、只撤旧样本和标记 (改指之后的、只差空白的、"
          "源清空的不动), 跑两遍不多删, 默认授权下备份表也收住, 回滚都对 ✓")


def s7_batch3_rows() -> None:
    """#111 / #112 的查询写坏了只会显示 N/A (safe_count 吞错), 底数 0 在 §0 已核; 这里再核它们真数得对。都在事务里, 回滚。"""
    swap = ("BEGIN;\nALTER VIEW truth_vault.v_flywheel_lesson_cards RENAME TO v_flywheel_lesson_cards_ci_real;\n"
            "CREATE VIEW truth_vault.v_flywheel_lesson_cards AS SELECT * FROM (VALUES (NULL::float8, 0.2::float8), "
            "(0.5, 1.5), (0.5, -0.1), (0.5, NULL), (0.5, 0.0), (0.5, 1.0)) t(rank_score, account_prior);\n")
    want(verify(swap, "\nROLLBACK;\n"), "111", "4", "空 rank_score 1 张 + 先验 > 1、< 0、为空各 1 张; 先验正好 0 和 1 不算")
    na = "BEGIN;\nALTER TABLE truth_vault.v_flywheel_lesson_cards RENAME COLUMN account_prior TO account_prior_ci;\n"
    want(verify(na, "\nROLLBACK;\n"), "111", "N/A", "书架视图没有 account_prior 列 (v1_34 没跑)")
    want(verify("BEGIN;\nGRANT SELECT ON truth_vault.v_l2_outcomes TO anon;\n", "\nROLLBACK;\n"), "112", "1", "anon 能读")
    want(verify("BEGIN;\nGRANT SELECT ON truth_vault.v_l2_outcomes TO anon, authenticated;\n", "\nROLLBACK;\n"),
         "112", "2", "anon、authenticated 都能读")
    got = verify()
    want(got, "111", "0", "事务回滚之后")
    want(got, "112", "0", "事务回滚之后")
    print("  §7 #111 书架空分 / 先验越界数得对 (边界 0、1 不算), 没列 → N/A · #112 anon / authenticated 能读 v_l2_outcomes 数得对 ✓")


RP_BLOCK = re.compile(r"WITH rp AS \((.*?)GROUP BY a\.row_id", re.S)
RULE3 = "AND (n.raw_extra ? '_comment_text' OR n.raw_extra ? '_comment_text_persona' OR rp.pt_changed)"


def s6_rule_text() -> None:
    """改指的认法抄在 7 处 (verify #109 / #110、cleanup 两处、withdraw 三处); 行为夹具只能抽查, 这里逐字比。"""
    texts = {name: (HERE / name).read_text(encoding="utf-8") for name in (
        "verify_supabase_state.sql", "cleanup_repointed_stale_comments_au_f02b.sql",
        "withdraw_repointed_stale_ssll_samples_au_f02b.sql")}
    blocks = []
    for name, t in texts.items():
        blocks += [(name, " ".join(b.split())) for b in RP_BLOCK.findall(t)]
    want_n = {"verify_supabase_state.sql": 2, "cleanup_repointed_stale_comments_au_f02b.sql": 2,
              "withdraw_repointed_stale_ssll_samples_au_f02b.sql": 3}
    for name, n in want_n.items():
        got_n = sum(1 for b in blocks if b[0] == name)
        if got_n != n:
            raise SystemExit(f"❌ §6 {name} 里应有 {n} 段 WITH rp AS (...), 实际 {got_n}")
    if len({b for _, b in blocks}) != 1:
        raise SystemExit("❌ §6 改指的认法 (WITH rp AS 那一段) 在几处不一样:\n  " +
                         "\n  ".join(f"{n}: {b[:160]}…" for n, b in blocks))
    if "btrim(a.changed_cols->'publish_url'->>0" not in blocks[0][1] or "pt_changed" not in blocks[0][1]:
        raise SystemExit("❌ §6 改指的认法里没有 btrim 或 pt_changed")
    rule3 = " ".join(RULE3.split())
    flat = {n: " ".join(t.split()) for n, t in texts.items()}
    need = {"verify_supabase_state.sql": 1, "cleanup_repointed_stale_comments_au_f02b.sql": 1,
            "withdraw_repointed_stale_ssll_samples_au_f02b.sql": 1}
    for name, n in need.items():
        if flat[name].count(rule3) != n:
            raise SystemExit(f"❌ §6 {name} 里「第 ③ 条」({RULE3}) 应出现 {n} 次, 实际 {flat[name].count(rule3)}")
    print("  §6 改指的认法 7 处一字不差 (带 btrim), 第 ③ 条在 #109、cleanup、withdraw 的检查里都有 ✓")


if __name__ == "__main__":
    sys.exit(main())
