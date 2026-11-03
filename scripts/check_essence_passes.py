"""夜跑 essence 两趟 + 时限的自检 (D-143, 2026-11-03)。CI 里一行调用 (ci.yml 不再加内联块, D-075)。

D-137 之后 OKMAN 268 篇真改过正文的旧篇要几晚才消完, 中转站慢的那一小时 (约 96 秒一篇) 一来, 按字母序排在后面的项目
当晚的新篇会被时限挤掉。夜跑改成两趟 (先所有项目的新篇, 再正文改过的) + 时限。这里钉住脚本那一半和 workflow 接线。
在 scripts/ 下跑: python check_essence_passes.py
"""
import sys, time, pathlib, yaml
import annotate_essence_pass as a
seen = {}
built = []
new_note = {"note_id": "N1", "projects": {}}
stale_note = {"note_id": "S1", "projects": {}, "_essence_stale": True}
def fake_fetch(sb, pid, reannotate, only_missing_subtype=False, mapping=None, include_stale=True):
    seen["include_stale"] = include_stale
    return [dict(new_note)] + ([dict(stale_note)] if include_stale else [])
a.fetch_unannotated_notes = fake_fetch
a.load_mapping = lambda pid: {}
a.get_supabase_client = lambda: None
a.build_mode_a_prompt = lambda info, note: (built.append(note["note_id"]) or ("sys", "user"))
def run(*extra):
    built.clear(); seen.clear()
    sys.argv = ["annotate_essence_pass.py", "P", "--dry-run", "--failed-queue", "/tmp/fq.jsonl", *extra]
    return a.main()
assert run("--pass", "new") == 0 and seen["include_stale"] is False and built == ["N1"]
print("  ✓ --pass new: 只取没标过的 (include_stale=False)")
assert run("--pass", "stale") == 0 and seen["include_stale"] is True and built == ["S1"]
print("  ✓ --pass stale: 只重标正文改过的")
assert run() == 0 and built == ["N1", "S1"]
print("  ✓ 默认 all: 没标过的在前、过期的在后 (和以前一样)")
assert run("--deadline-epoch", str(time.time() - 1)) == 0 and built == []
print("  ✓ 过了时限: 一篇都不开标, 退 0 (下一晚幂等续标)")
assert run("--deadline-epoch", str(time.time() + 3600)) == 0 and built == ["N1", "S1"]
print("  ✓ 没到时限照常标")
for bad in (["--pass", "new", "--reannotate"], ["--pass", "stale", "--only-missing-subtype"]):
    try:
        run(*bad)
        raise AssertionError(f"{bad} 应该被拒")
    except SystemExit as e:
        assert e.code == 2, e.code
print("  ✓ --pass new / stale 不能和 --reannotate / --only-missing-subtype 一起用")

wf = yaml.safe_load(pathlib.Path("../.github/workflows/daily-sync.yml").read_text())
ess = [s for s in wf["jobs"]["sync"]["steps"] if s.get("id") == "essence_sync"][0]
code = "\n".join(l for l in ess["run"].splitlines() if not l.strip().startswith("#"))
assert "for pass in new stale; do" in code, "essence 要先跑新篇这一趟, 再跑正文改过的那一趟"
assert code.count("--deadline-epoch \"$ESS_DEADLINE\"") == 2, "两趟都要带时限"
assert "TV_JOB_STARTED_AT" in code and "180 * 60" in code, "时限按开工时间算 (job 上限 240 分钟, 后面几步还要时间)"
assert "--pass new" in code and "--pass stale" in code
assert code.index("--pass new") > code.index("skip_on_cron.py"), "新篇那一趟也要过 on_demand 闸"
assert "WORKER_LIMIT - ${ESS_NEW_FOUND[$p]:-0}" in code, "两趟加起来不超过每项目的日上限"
print("  ✓ daily-sync 的 essence 两趟 + 时限已接上, 每项目上限两趟合计")
print("\nessence passes + deadline: all checks passed")
