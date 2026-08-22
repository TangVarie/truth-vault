"""deskcore/core.py — 写作台内核的纯函数层。

不 import FastAPI, 不 import MCP SDK —— 这样 cli.py 能直接调、能 --dry-run,
跟 librarian/core.py 同一个形状(那边 CLI 和 HTTP 是同一个 librarian_select 的
两个 adapter, MCP 是第三个)。

搬过来的四个机制及其出处(autowriter 仓):
  1. 分层硬约束      memory.py:131  build_layered_system_prompt
  2. 调校笔记萃取    memory.py:1154 generate_calibration_notes
  3. 正负例池        db.py:2169     list_example_items
  4. 语义查重        dedup.py + app.py:456

三处【刻意的改动】(不是照搬, 是修根因, 见 docs/27):
  A. 正例不再 created_at DESC 取 5 —— 改按相关性检索 + lever 多样性约束。
     原实现构成趋同回路: 模型模仿最近 5 条 → 新稿被标 positive → 窗口滚动
     → 语感越收越窄。
  B. 查重不再只看最近 20 条, 也不再只比标题 —— 比【全量】历史的标题语义 +
     开头指纹 + 跨篇四字串。
  C. 查重是【硬闸】—— 命中就 reject, 不是写条警告了事
     (autowriter 的 ENABLE_DEDUP_REGEN 默认 "0", 查重跑了但不拦)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone

from . import clients, vocab

logger = logging.getLogger("deskcore")

# 一次最多给模型几条正例 —— 与 autowriter build_layered_system_prompt 的 [:5] 对齐。
MAX_POSITIVE = 5
MAX_NEGATIVE = 3

# 查重阈值。autowriter 用 0.92 且只比标题, 实测换个说法的同角度标题普遍落在
# 0.85-0.90 全部溜过(见 docs/27 根因 2)。这里下调到 0.86, 并且标题只是三个
# 信号之一 —— 单独一个信号命中不判死, 见 _verdict()。
TITLE_SIM_HARD = 0.90     # 单看标题就足以判重
TITLE_SIM_WARN = 0.84     # 进入"可疑", 需要第二个信号佐证
NGRAM_JACCARD_HARD = 0.35 # 正文四字串重合度; 超过这个基本是同一篇换皮
NGRAM_JACCARD_WARN = 0.22


# ══════════════════════════════════════════════════════════════════════
# 项目与规则
# ══════════════════════════════════════════════════════════════════════

def _fetch_project(sb, project_id: str) -> dict | None:
    res = (sb.table("projects")
             .select("id, name, brand, system_prompt, system_prompt_tone, "
                     "system_prompt_exec, tactics, calibration_notes, custom_roles")
             .eq("id", project_id).limit(1).execute())
    rows = res.data or []
    return rows[0] if rows else None


def _parse_json_field(raw, default):
    """projects.tactics / custom_roles 是 JSONB, 但历史上存过字符串。"""
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def list_projects(sb) -> list[dict]:
    """项目清单 + 每个项目手上有多少料。

    计数用 count='exact' + limit(1), 不把行拉回来 —— 40 个项目 × 4 次查询,
    拉行会很慢。
    """
    res = sb.table("projects").select("id, name, brand").order("name").execute()
    out = []
    for p in (res.data or []):
        pid = p["id"]
        try:
            rules = (sb.table("memories").select("id", count="exact")
                       .eq("project_id", pid).eq("status", "confirmed")
                       .limit(1).execute()).count or 0
        except Exception:
            logger.exception("count memories failed for %s", pid)
            rules = 0
        try:
            fps = (sb.table("draft_fingerprints").select("id", count="exact")
                     .eq("project_id", pid).limit(1).execute()).count or 0
        except Exception:
            fps = 0
        out.append({
            "project_id": pid,
            "name": p.get("name") or "",
            "brand": p.get("brand") or "",
            "rule_count": rules,
            "fingerprint_count": fps,
        })
    return out


def _fetch_memories(sb, project_id: str) -> tuple[list[dict], list[dict]]:
    """规则层。返回 (hard, soft)。

    【共享口径】: 按 project_id 读全量, 不按 user_id 过滤 —— 项目硬约束是团队
    资产, 一个人定的规则别人也该守(用户 2026-08-22 拍板)。
    autowriter 原来靠 RLS 按 user_id 隔离, deskcore 持 service_role 自己执行口径。

    同时取 scope='global' 的通用规则(那些不绑项目)。
    """
    def _rows(query):
        try:
            return (query.eq("status", "confirmed").execute()).data or []
        except Exception:
            logger.exception("fetch memories failed")
            return []

    proj = _rows(sb.table("memories")
                   .select("id, content, severity, scope, rule_kind, rule_payload, muted_until")
                   .eq("project_id", project_id).eq("scope", "project"))
    glob = _rows(sb.table("memories")
                   .select("id, content, severity, scope, rule_kind, rule_payload, muted_until")
                   .eq("scope", "global"))

    now = datetime.now(timezone.utc)

    def _active(m: dict) -> bool:
        mu = m.get("muted_until")
        if not mu:
            return True
        try:
            return datetime.fromisoformat(str(mu).replace("Z", "+00:00")) < now
        except (ValueError, TypeError):
            return True

    all_rows = [m for m in (glob + proj) if _active(m) and (m.get("content") or "").strip()]
    hard = [m for m in all_rows if (m.get("severity") or "soft").lower() == "hard"]
    soft = [m for m in all_rows if (m.get("severity") or "soft").lower() != "hard"]
    return hard, soft


# ══════════════════════════════════════════════════════════════════════
# 正负例 —— 改动 A: 相关性检索取代 recency top-5
# ══════════════════════════════════════════════════════════════════════

def _fetch_labeled(sb, project_id: str, label: str, user_id: str | None,
                   pool_size: int = 60) -> list[dict]:
    """取候选正/负例。

    走 PostgREST embedded inner join(batches!inner(project_id)) —— 这是
    autowriter db.py:2176-2180 的做法, 绕开"最近 50 batch 窗口"的坑。

    user_id 非空时只取本人的 —— 【私有口径】: 正负例是个人风格资产。
    """
    q = (sb.table("items")
           .select("id, best_version_id, created_at, user_id, "
                   "versions(id, title, body, version_num, embedding), "
                   "batches!inner(project_id)")
           .eq("batches.project_id", project_id)
           .eq("example_label", label)
           .order("created_at", desc=True)
           .limit(pool_size))
    if user_id:
        q = q.eq("user_id", user_id)
    try:
        res = q.execute()
    except Exception:
        logger.exception("fetch %s examples failed", label)
        return []

    out = []
    for item in (res.data or []):
        versions = item.get("versions") or []
        if not versions:
            continue
        best_id = item.get("best_version_id")
        chosen = next((v for v in versions if v.get("id") == best_id), None)
        if chosen is None:
            chosen = max(versions, key=lambda v: v.get("version_num") or 0)
        title = (chosen.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "item_id": item["id"],
            "version_id": chosen.get("id"),
            "title": title,
            "body": chosen.get("body") or "",
            "embedding": chosen.get("embedding"),
            "created_at": item.get("created_at"),
        })
    return out


def _brief_text(brief: dict) -> str:
    """把本次写作意图拼成一段可 embed 的文本。"""
    parts = [
        brief.get("tactic") or "",
        brief.get("draft_topic") or "",
        brief.get("key_messages") or "",
        brief.get("target_audience") or "",
        brief.get("tone") or "",
        brief.get("extra_instructions") or "",
    ]
    return "\n".join(p for p in parts if p).strip()


def select_positive_examples(candidates: list[dict], brief: dict,
                             limit: int = MAX_POSITIVE) -> list[dict]:
    """按相关性 + 多样性挑正例, 而不是 created_at DESC 取前 N。

    为什么改(docs/27 根因 4): 原 recency top-5 构成趋同回路 —— 模型模仿最近
    5 条 → 新稿被标 positive → 窗口滚动 → 语感越收越窄。而监控这件事的
    check_positive_saturation.py 因为只统计 external_source='truth_vault'
    (那列全 NULL), 永远打印"没有正例", 这个回路从来没被任何人看见过。

    怎么改:
      · 有 brief 且能算 embedding → 按与 brief 的余弦相关性排序
      · 没有 → 退化成 recency(与原行为一致, 不会更差)
      · 两种情况都跑一遍多样性约束: 先每个"开头指纹"只收第一条, 再补满。
        这一步是从 sync_truth_vault_baokuan_to_autowriter_items.py:211-269
        的两趟贪心搬来的, 但那边 min_levers 只是 advisory 不拒绝,
        这里是真约束(单一开头形态最多占一半)。
    """
    if not candidates:
        return []

    ranked = candidates
    brief_text = _brief_text(brief)
    if brief_text and clients.embeddings_available():
        vecs = clients.embed_texts([brief_text])
        if vecs:
            bvec = vecs[0]
            scored = []
            for c in candidates:
                emb = c.get("embedding")
                # 历史 version 没算过向量的排在后面, 但不丢弃 —— 否则新项目
                # (向量还没回填)会一条正例都取不到。
                score = clients.cosine(bvec, emb) if emb else -1.0
                scored.append((score, c))
            scored.sort(key=lambda t: t[0], reverse=True)
            ranked = [c for _s, c in scored]

    # 多样性: 按开头形态分桶, 第一趟每桶只取一条。
    seen_shape: set[str] = set()
    first_pass: list[dict] = []
    rest: list[dict] = []
    for c in ranked:
        shape = clients.sha16(clients.normalize_text(clients.opening_of(c["body"], 12)))
        if shape in seen_shape:
            rest.append(c)
        else:
            seen_shape.add(shape)
            first_pass.append(c)

    picked = first_pass[:limit]
    if len(picked) < limit:
        picked += rest[: limit - len(picked)]
    return picked


# ══════════════════════════════════════════════════════════════════════
# 分层写作简报 —— 搬 build_layered_system_prompt
# ══════════════════════════════════════════════════════════════════════

def build_brief(sb, project_id: str, *, user_id: str | None = None,
                brief: dict | None = None) -> dict:
    """一次返回完整写作简报 —— 治"一个项目 5 个提示词要点 5 次"。

    分层与 autowriter memory.py:131-267 一致, 语义也保持:
      stable  项目人格(几乎不变)
      tactic  战术
      p0      硬约束 —— 顶一句"必须 100% 满足"。规则不忘就靠这层【每次重注入】
      p1      软偏好 + 调校笔记 + 正反例
      p2      会话临时指令(由调用方自己管, 这里不产出)

    与原实现的差别: calibration 分两段 —— 项目共享基线 + 我的个人叠加。
    """
    brief = brief or {}
    project = _fetch_project(sb, project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")

    hard, soft = _fetch_memories(sb, project_id)
    positives_pool = _fetch_labeled(sb, project_id, "positive", user_id)
    positives = select_positive_examples(positives_pool, brief)
    negatives = _fetch_labeled(sb, project_id, "negative", user_id)[:MAX_NEGATIVE]

    shared_calib = (project.get("calibration_notes") or "").strip()
    my_calib = ""
    if user_id:
        try:
            r = (sb.table("user_calibration_notes").select("notes")
                   .eq("project_id", project_id).eq("user_id", user_id)
                   .limit(1).execute())
            if r.data:
                my_calib = (r.data[0].get("notes") or "").strip()
        except Exception:
            logger.exception("fetch user calibration failed")

    # ── stable ──
    tone = (project.get("system_prompt_tone") or "").strip()
    execp = (project.get("system_prompt_exec") or "").strip()
    base = (project.get("system_prompt") or "").strip()
    stable_parts = [p for p in (base, tone, execp) if p]
    # tone/exec 是 base 拆出来的两半(projects.py:367-369 保存时会合成 base),
    # 都有值时优先用拆开的两半, 免得同样内容出现两遍。
    if tone or execp:
        stable_parts = [p for p in (tone, execp) if p] or [base]
    stable = "\n\n".join(stable_parts)

    # ── p0 硬约束 ──
    p0 = ""
    if hard:
        lines = "\n".join(f"• {m['content']}" for m in hard)
        p0 = ("---【P0 · 不可违反的硬约束】---\n"
              "本节每一条都必须 100% 满足；若与下方偏好冲突，以此节为准。\n\n" + lines)

    # ── p1 软偏好 + 调校 + 正反例 ──
    p1_sections: list[str] = []
    if soft:
        p1_sections.append("[项目偏好]\n" + "\n".join(f"• {m['content']}" for m in soft))
    if shared_calib:
        p1_sections.append(f"[调校笔记 · 项目共享基线]\n{shared_calib}")
    if my_calib:
        p1_sections.append(
            f"[调校笔记 · 我的个人风格]\n"
            f"以下是从我手动改稿里提炼的个人语感。与项目基线冲突时以本节为准。\n{my_calib}")
    if positives:
        blocks = []
        for ex in positives:
            preview = (ex["body"] or "")[:200].split("\n")[0]
            blocks.append(f"标题：{ex['title']}\n正文节选：{preview}")
        p1_sections.append(
            "[优质正案例 · 学习风格/结构/切入]\n"
            "严禁直接复用例子里的标题主干、开场句、具体比喻；只可借鉴节奏与角度。\n"
            + "\n\n".join(blocks))
    if negatives:
        blocks = []
        for ex in negatives:
            preview = (ex["body"] or "")[:120].split("\n")[0]
            blocks.append(f"标题：{ex['title']}\n正文节选：{preview}")
        p1_sections.append("[反面案例 · 主动规避]\n" + "\n\n".join(blocks))

    p1 = ""
    if p1_sections:
        p1 = ("---【P1 · 项目调性偏好】---\n"
              "请理解每条意图、在本批适用时再应用；明显不适用时可以让位，"
              "不必为了套用规则扭曲文案。与 P0 冲突时以 P0 为准。\n\n"
              + "\n\n".join(p1_sections))

    return {
        "project_id": project_id,
        "project_name": project.get("name") or "",
        "brand": project.get("brand") or "",
        "stable": stable,
        "tactics": _parse_json_field(project.get("tactics"), []),
        "p0": p0,
        "p1": p1,
        "counts": {
            "hard_rules": len(hard),
            "soft_rules": len(soft),
            "positive_examples": len(positives),
            "positive_pool": len(positives_pool),
            "negative_examples": len(negatives),
            "has_shared_calibration": bool(shared_calib),
            "has_personal_calibration": bool(my_calib),
        },
        "positive_selection_mode": (
            "relevance" if (_brief_text(brief) and clients.embeddings_available())
            else "recency_fallback"
        ),
    }


# ══════════════════════════════════════════════════════════════════════
# 发牌 —— 恢复 _assign_slot_coordinates, 但加跨批次台账
# ══════════════════════════════════════════════════════════════════════

def angle_key(dims: dict) -> str:
    """dims 的规范化指纹。只取参与无放回抽样的四个主维度。

    trend/intensity/tilt 是叠加项不进 key —— 否则同一个核心组合换个词感就
    被当成"没用过", 台账就白记了。
    """
    core = "|".join(str(dims.get(k, "")) for k in
                    ("emotional_lever", "human_truth_archetype",
                     "content_format", "title_structure"))
    return hashlib.sha256(core.encode("utf-8")).hexdigest()[:20]


def _recent_angle_keys(sb, project_id: str, avoid_days: int) -> set[str]:
    """台账里近期用过的组合。

    consumed(真出了稿)按 avoid_days 算; 只抽没用(占位)的按 1 天算 —— 抽了没
    写的不该长期占着坑位, 否则连点几次发牌就把组合空间锁死了。
    """
    since = (datetime.now(timezone.utc) - timedelta(days=avoid_days)).isoformat()
    placeholder_since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    keys: set[str] = set()
    try:
        used = (sb.table("angle_ledger").select("angle_key")
                  .eq("project_id", project_id)
                  .not_.is_("consumed_version_id", "null")
                  .gte("drawn_at", since).execute()).data or []
        keys.update(r["angle_key"] for r in used)
        held = (sb.table("angle_ledger").select("angle_key")
                  .eq("project_id", project_id)
                  .is_("consumed_version_id", "null")
                  .gte("drawn_at", placeholder_since).execute()).data or []
        keys.update(r["angle_key"] for r in held)
    except Exception:
        logger.exception("read angle ledger failed; drawing without history avoidance")
    return keys


def draw_angles(sb, project_id: str, n: int, *, avoid_days: int = 30,
                user_id: str | None = None, seed: int | None = None,
                perpetual_bias: bool = False) -> list[dict]:
    """发 n 张互不重复、且避开台账的创作坐标, 写入台账。

    这是 autowriter _assign_slot_coordinates(generator.py:1301) 的复活版。
    当年它被移除(generator.py:1576-1584)的理由是"跟项目自己的 role 设定打架
    —— LLM 会锁定更具体的平台标签, 把项目的 role 降级成风格提示"。
    修法: 切入角度优先用项目自己的 custom_roles, 没配才用通用池。这正是
    当年注释里留的那条路("future iteration wants them back behind a
    per-project opt-in flag")。
    """
    if n <= 0:
        return []
    project = _fetch_project(sb, project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")

    custom = _parse_json_field(project.get("custom_roles"), [])
    angles = custom if custom else list(vocab.DEFAULT_ANGLES)

    rng = random.Random(seed) if seed is not None else random.Random()
    avoid = _recent_angle_keys(sb, project_id, avoid_days)

    # 主维度笛卡尔积 → 打散 → 依次挑没用过的。空间 14592, 20-50 条离撞车很远。
    space = [
        (lever, arche, fmt, struct)
        for lever in vocab.EMOTIONAL_LEVERS
        for arche in vocab.HUMAN_TRUTH_ARCHETYPES
        for fmt in vocab.CONTENT_FORMATS
        for struct in vocab.TITLE_STRUCTURES
    ]
    rng.shuffle(space)

    tilt = rng.choice(vocab.WORD_TILTS)  # 词感是"今天的心情", 全批一致
    picked: list[dict] = []
    used_this_call: set[str] = set()
    exhausted = False

    for combo in space:
        if len(picked) >= n:
            break
        lever, arche, fmt, struct = combo
        dims = {
            "emotional_lever": lever,
            "human_truth_archetype": arche,
            "content_format": fmt,
            "title_structure": struct,
        }
        key = angle_key(dims)
        if key in avoid or key in used_this_call:
            continue
        used_this_call.add(key)

        angle = angles[len(picked) % len(angles)]
        trends = ([vocab.TREND_EXCLUSIVE] if perpetual_bias
                  else vocab.normalize_trends([rng.choice(vocab.TREND_DEPENDENCIES)]))
        picked.append({
            "slot": len(picked) + 1,
            "angle_key": key,
            "dims": dims,
            "emotional_valence": vocab.valence_of(lever),
            "emotional_intensity": rng.choice(vocab.EMOTIONAL_INTENSITIES),
            "trend_dependencies": trends,
            "word_tilt": tilt,
            "angle_name": angle.get("name") or angle.get("id") or "",
            "angle_brief": angle.get("brief") or angle.get("prompt_suffix") or "",
            "boundary_rule": vocab.boundary_rules_for(lever),
        })

    if len(picked) < n:
        exhausted = True
        logger.warning(
            "angle space exhausted for project %s: asked %d, got %d "
            "(avoid set size %d). Consider raising avoid_days or widening vocab.",
            project_id, n, len(picked), len(avoid))

    # 写台账。失败不阻塞发牌 —— 但必须留痕, 否则下次避重会静默失效。
    if picked:
        rows = [{
            "project_id": project_id,
            "angle_key": p["angle_key"],
            "dims": p["dims"],
            "drawn_by": user_id,
        } for p in picked]
        try:
            sb.table("angle_ledger").insert(rows).execute()
        except Exception:
            logger.exception("write angle_ledger failed; cross-batch avoidance "
                             "will not see this draw")

    return picked


def render_angles_block(angles: list[dict]) -> str:
    """把发牌结果渲染成可直接贴进 prompt 的硬约束块。

    照 _build_slot_coordinates_block(generator.py:1350) 的形状, 但多带
    essence 维度和边界判据 —— 光给标签名模型会混(docs/05 花 40 行讲焦虑 vs
    恐惧怎么分是有原因的)。
    """
    if not angles:
        return ""
    lines = ["【本批次每篇的创作坐标（必须按编号对应，不得互换）】"]
    for a in angles:
        d = a["dims"]
        seg = (f"第{a['slot']}篇："
               f"情绪杠杆={d['emotional_lever']}({a['emotional_valence']}/{a['emotional_intensity']})"
               f" · 人性原型={d['human_truth_archetype']}"
               f" · 内容形式={d['content_format']}"
               f" · 标题句式={d['title_structure']}"
               f" · 切入角度={a['angle_name']}")
        lines.append(seg)
        if a.get("boundary_rule"):
            lines.append(f"    ↳ 判据：{a['boundary_rule']}")
        if a.get("angle_brief"):
            lines.append(f"    ↳ 角度：{a['angle_brief']}")
    lines.append(f"\n全批词感倾向：{angles[0].get('word_tilt', '')}")
    lines.append("以上坐标为硬约束。写完后每一篇要能说出自己用的是哪一组，说不出就是没按坐标写。")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 查重硬闸 —— 改动 B + C
# ══════════════════════════════════════════════════════════════════════

def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fetch_fingerprints(sb, project_id: str, limit: int = 4000) -> list[dict]:
    """取项目【全量】历史指纹。

    与 autowriter 的两个限制对照:
      · 它的 queue_embeddings 是 worker 进程内的内存字典(app.py:1024),
        进程一重启就空了 —— 而 jobs 表那条 migration 的存在本身就说明
        进程重启很频繁。
      · 它给模型看的避重清单是 historical[-20:](generator.py:1384),
        从库里捞的 150 条扔掉 130 条。
    这里是持久表 + 全量比对; limit 4000 只是防单项目十万行时把内存打爆,
    真到那天该上 pgvector 服务端检索(见 docs/27 未决点)。
    """
    try:
        res = (sb.table("draft_fingerprints")
                 .select("id, title, opening, title_embedding, opening_hash, "
                         "ngram_hashes, created_at")
                 .eq("project_id", project_id)
                 .order("created_at", desc=True)
                 .limit(limit).execute())
        return res.data or []
    except Exception:
        # 查重读不到 = 不能放行。这里【故意抛】, 不 fail-open。
        logger.exception("fetch fingerprints failed for project %s", project_id)
        raise


def _verdict(title_sim: float, opening_exact: bool, ngram_j: float) -> tuple[str, str]:
    """三个信号合议出结论。

    为什么不是单信号判死: autowriter 用 0.92 的标题余弦单独判, 换个说法的
    同角度标题普遍落在 0.85-0.90 全部溜过(docs/27 根因 2)。这里把阈值下调,
    但要求"一个强信号"或"两个弱信号"才判 reject, 避免误伤合法的角度变体。
    """
    if opening_exact:
        return "reject", "正文开头与历史稿完全一致"
    if title_sim >= TITLE_SIM_HARD:
        return "reject", f"标题语义与历史稿高度重合(cos={title_sim:.3f})"
    if ngram_j >= NGRAM_JACCARD_HARD:
        return "reject", f"正文与历史稿大面积重合(四字串 Jaccard={ngram_j:.3f})"
    weak = 0
    reasons = []
    if title_sim >= TITLE_SIM_WARN:
        weak += 1
        reasons.append(f"标题接近(cos={title_sim:.3f})")
    if ngram_j >= NGRAM_JACCARD_WARN:
        weak += 1
        reasons.append(f"正文用词接近(Jaccard={ngram_j:.3f})")
    if weak >= 2:
        return "reject", "；".join(reasons) + " —— 两项同时接近"
    if weak == 1:
        return "warn", reasons[0]
    return "pass", ""


def check_drafts(sb, project_id: str, drafts: list[dict]) -> dict:
    """硬闸: 比对全量历史 + 本批内互比。

    ⚠️ 这是 deskcore 唯一【不 fail-open】的工具。其它读类工具出错返回空结构
    不阻塞写稿, 但查重挂了必须报错 —— 静默放行就是重演 autowriter 那个
    ENABLE_DEDUP_REGEN 默认关着、查重跑了但不拦的老问题(docs/27 根因 1)。

    drafts: [{"title": str, "body": str, "angle_key": str?}, ...]
    """
    if not drafts:
        return {"results": [], "summary": {"total": 0, "pass": 0, "warn": 0, "reject": 0}}

    history = _fetch_fingerprints(sb, project_id)

    titles = [(d.get("title") or "").strip() for d in drafts]
    bodies = [d.get("body") or "" for d in drafts]
    openings = [clients.opening_of(b) for b in bodies]
    opening_hashes = [clients.sha16(clients.normalize_text(o)) for o in openings]
    ngrams = [set(clients.ngram_hashes(b)) for b in bodies]

    # 语义信号是可选的; 没有 embedding 就靠两个确定性信号, 并明确告知降级。
    new_vecs = clients.embed_texts(titles) if clients.embeddings_available() else None
    degraded = new_vecs is None
    if degraded:
        logger.warning("semantic dedup degraded to deterministic-only for project %s",
                       project_id)

    hist_ngrams = [set(h.get("ngram_hashes") or []) for h in history]
    hist_opening = {h.get("opening_hash"): h for h in history if h.get("opening_hash")}

    results = []
    for i, d in enumerate(drafts):
        best_sim, best_hit = 0.0, None
        if new_vecs and i < len(new_vecs):
            for h in history:
                emb = h.get("title_embedding")
                if not emb:
                    continue
                s = clients.cosine(new_vecs[i], emb)
                if s > best_sim:
                    best_sim, best_hit = s, h

        best_j, best_j_hit = 0.0, None
        for hi, hg in enumerate(hist_ngrams):
            j = _jaccard(ngrams[i], hg)
            if j > best_j:
                best_j, best_j_hit = j, history[hi]

        exact = opening_hashes[i] in hist_opening
        opening_hit = hist_opening.get(opening_hashes[i])

        # 本批内互比: 前面的稿子也算历史(同批两篇撞车同样要拦)。
        intra_hit = None
        for j2 in range(i):
            if opening_hashes[i] == opening_hashes[j2]:
                exact, intra_hit = True, titles[j2]
                break
            jj = _jaccard(ngrams[i], ngrams[j2])
            if jj > best_j:
                best_j, best_j_hit, intra_hit = jj, None, titles[j2]
            if new_vecs:
                s = clients.cosine(new_vecs[i], new_vecs[j2])
                if s > best_sim:
                    best_sim, best_hit, intra_hit = s, None, titles[j2]

        status, reason = _verdict(best_sim, exact, best_j)
        collided = (
            intra_hit
            or (opening_hit or {}).get("title")
            or (best_hit or {}).get("title")
            or (best_j_hit or {}).get("title")
            or ""
        )
        results.append({
            "index": i,
            "title": titles[i],
            "status": status,
            "reason": reason,
            "collided_with": collided,
            "collided_scope": "本批内" if intra_hit else ("历史" if collided else ""),
            "signals": {
                "title_similarity": round(best_sim, 4),
                "opening_exact_match": exact,
                "body_ngram_jaccard": round(best_j, 4),
            },
        })

    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "warn": sum(1 for r in results if r["status"] == "warn"),
        "reject": sum(1 for r in results if r["status"] == "reject"),
        "history_size": len(history),
        "semantic_degraded": degraded,
    }
    if degraded:
        summary["degraded_note"] = (
            "GOOGLE_API_KEY 未配或 embedding 调用失败, 本次只跑了确定性查重"
            "(开头精确 + 四字串重合)。同角度换说法的标题可能漏过。")
    return {"results": results, "summary": summary}


def commit_drafts(sb, project_id: str, drafts: list[dict], *,
                  user_id: str | None = None) -> dict:
    """定稿入库: 写指纹 + 把用掉的角度组合标记为已消耗。

    只收真正定稿的稿子 —— 指纹库脏了(把废稿也记进去)会让后续正常选题被误杀。
    """
    if not drafts:
        return {"written": 0, "consumed_angles": 0}

    titles = [(d.get("title") or "").strip() for d in drafts]
    vecs = clients.embed_texts(titles) if clients.embeddings_available() else None

    rows = []
    for i, d in enumerate(drafts):
        body = d.get("body") or ""
        rows.append({
            "project_id": project_id,
            "version_id": d.get("version_id"),
            "user_id": user_id,
            "title": titles[i],
            "opening": clients.opening_of(body),
            "title_embedding": vecs[i] if vecs and i < len(vecs) else None,
            "opening_hash": clients.sha16(clients.normalize_text(clients.opening_of(body))),
            "ngram_hashes": clients.ngram_hashes(body),
            "angle_key": d.get("angle_key"),
        })
    sb.table("draft_fingerprints").insert(rows).execute()

    consumed = 0
    for d in drafts:
        key = d.get("angle_key")
        if not key:
            continue
        try:
            (sb.table("angle_ledger")
               .update({"consumed_version_id": d.get("version_id") or _placeholder_uuid(key),
                        "consumed_at": clients.iso_now()})
               .eq("project_id", project_id).eq("angle_key", key)
               .is_("consumed_version_id", "null").execute())
            consumed += 1
        except Exception:
            logger.exception("mark angle consumed failed: %s", key)

    return {"written": len(rows), "consumed_angles": consumed}


def _placeholder_uuid(seed: str) -> str:
    """没有真实 version_id 时(在 WorkBuddy 里写稿, 稿子不落 autowriter.versions)
    造一个确定性 UUID, 只为把 consumed_version_id 置成非 NULL 表示"用掉了"。"""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ══════════════════════════════════════════════════════════════════════
# 反馈学习
# ══════════════════════════════════════════════════════════════════════

def record_rule(sb, project_id: str, content: str, *, severity: str = "soft",
                scope: str = "project", user_id: str | None = None,
                rule_kind: str = "free_text") -> dict:
    """沉淀一条规则(团队共享)。severity='hard' 的下次进 P0。

    直接写 status='confirmed' —— MCP 这条路径是用户明确说"以后都这样"才调用的,
    不是脚本自动推的。autowriter 那边的 candidate/confirmed 两段式是为了给
    自动抽取的候选留人工复核, 这里没有自动抽取。
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("rule content must not be empty")
    severity = severity.lower()
    if severity not in ("hard", "soft"):
        raise ValueError("severity must be 'hard' or 'soft'")
    if scope not in ("project", "global"):
        raise ValueError("scope must be 'project' or 'global'")

    row = {
        "content": content,
        "severity": severity,
        "scope": scope,
        "status": "confirmed",
        "memory_type": "rule",
        "rule_kind": rule_kind,
        "project_id": project_id if scope == "project" else None,
        "user_id": user_id,
    }
    res = sb.table("memories").insert(row).execute()
    new_id = (res.data or [{}])[0].get("id")
    return {"memory_id": new_id, "severity": severity, "scope": scope, "content": content}


_CALIB_SYSTEM = """\
你在维护一份「个人写作调校笔记」。输入是同一个人对 AI 初稿做的手动精修 —— \
左边是 AI 写的，右边是这个人改成的样子。

你的任务：从这些改动里提炼出【这个人的语感偏好】，写成可执行的短句。

铁律：
1. 只写从改动里【看得出来】的偏好。看不出来就不写，宁可少写。
2. 不要复述具体内容（"把郁可唯改成了别的明星"没有价值）；要写模式\
（"倾向去掉明星名，用泛指的场景代替"）。
3. 每条一行，以动词开头，可以直接当写作指令用。
4. 合并同类项。如果新观察和已有笔记说的是一件事，改写已有那条让它更准，\
不要并列两条。
5. 与已有笔记冲突时，以新观察为准（人的偏好会变）。
6. 总长度控制在 20 行以内。超了就合并最弱的几条。

只输出笔记正文，不要解释，不要 markdown 标题。"""


def record_edit(sb, project_id: str, *, user_id: str,
                ai_title: str = "", ai_body: str = "",
                my_title: str = "", my_body: str = "",
                note: str | None = None, distill: bool = True) -> dict:
    """喂一条手动精修 diff —— 这是【信号 A, 最高权重】, "裂变"的入口。

    照 generate_calibration_notes(autowriter/memory.py:1154-1210) 的口径:
    只收人真的动手改了的对子。没改就通过的稿子【不算教学材料】——
    memory.py:1191-1194 明确拒绝从那里学, 理由是模型会从偶然选择里编造风格规则。
    """
    if not (my_title or my_body):
        raise ValueError("my_title/my_body must not both be empty")
    if (ai_title or "").strip() == (my_title or "").strip() and \
       (ai_body or "").strip() == (my_body or "").strip():
        return {"stored": False, "reason": "AI 版与手改版完全一致, 不是有效信号, 未入库"}

    sb.table("style_edits").insert({
        "project_id": project_id,
        "user_id": user_id,
        "ai_title": ai_title or "",
        "ai_body": ai_body or "",
        "my_title": my_title or "",
        "my_body": my_body or "",
        "note": note,
    }).execute()

    if not distill:
        return {"stored": True, "distilled": False}

    try:
        notes = distill_calibration(sb, project_id, user_id=user_id)
        return {"stored": True, "distilled": True, "notes": notes}
    except Exception:
        # 存下来了就没白费, 蒸馏失败下次 record_edit 会连着这条一起重算。
        logger.exception("calibration distillation failed (edit is stored, will retry)")
        return {"stored": True, "distilled": False,
                "warning": "diff 已入库, 但本次笔记蒸馏失败; 下次 record_edit 会一并重算"}


def distill_calibration(sb, project_id: str, *, user_id: str,
                        max_edits: int = 8) -> str:
    """把最近的精修 diff 蒸馏成个人调校笔记, 写回 user_calibration_notes。"""
    res = (sb.table("style_edits")
             .select("ai_title, ai_body, my_title, my_body, note")
             .eq("project_id", project_id).eq("user_id", user_id)
             .order("created_at", desc=True).limit(max_edits).execute())
    edits = res.data or []
    if not edits:
        return ""

    existing = ""
    r = (sb.table("user_calibration_notes").select("notes")
           .eq("project_id", project_id).eq("user_id", user_id).limit(1).execute())
    if r.data:
        existing = (r.data[0].get("notes") or "").strip()

    blocks = []
    for e in edits:
        blocks.append(
            "AI 原版：\n"
            f"  标题：{e.get('ai_title','')}\n"
            f"  正文：{(e.get('ai_body') or '')[:400]}\n"
            "手改版：\n"
            f"  标题：{e.get('my_title','')}\n"
            f"  正文：{(e.get('my_body') or '')[:400]}"
            + (f"\n  本人备注：{e['note']}" if e.get("note") else "")
        )
    prompt = (
        (f"【已有笔记】\n{existing}\n\n" if existing else "【已有笔记】（空，这是第一次）\n\n")
        + "【本次要吸收的手动精修】\n" + "\n\n---\n".join(blocks)
        + "\n\n请输出更新后的完整笔记。"
    )

    model = os.environ.get("DESKCORE_MODEL", "claude-sonnet-4-6")
    text = clients.call_anthropic(prompt, model, system=_CALIB_SYSTEM, max_tokens=1500)
    notes = (text or "").strip()
    if not notes:
        raise RuntimeError("distillation returned empty notes")

    (sb.table("user_calibration_notes")
       .upsert({"project_id": project_id, "user_id": user_id, "notes": notes},
               on_conflict="project_id,user_id").execute())
    try:
        (sb.table("style_edits").update({"distilled": True})
           .eq("project_id", project_id).eq("user_id", user_id)
           .eq("distilled", False).execute())
    except Exception:
        logger.exception("mark style_edits distilled failed (notes are saved)")
    return notes


def label_example(sb, item_id: str, label: str | None) -> dict:
    """标正/负例。label=None 撤销标记。

    只认 autowriter 已有的 example_label 语义(positive/negative)。负例【只取
    人工标注】—— D-040 讲得很清楚: 「赢」需要真的好, 「输」有太多无辜理由
    (撞流量墙/账号限流/时机), 从数据反推负例会把被埋没的好内容也标成垃圾。
    """
    if label not in ("positive", "negative", None):
        raise ValueError("label must be 'positive', 'negative' or None")
    sb.table("items").update({"example_label": label}).eq("id", item_id).execute()
    return {"item_id": item_id, "example_label": label}


def my_style(sb, project_id: str, *, user_id: str) -> dict:
    """看我在这个项目上的风格资产。"""
    shared = ""
    project = _fetch_project(sb, project_id)
    if project:
        shared = (project.get("calibration_notes") or "").strip()

    mine = ""
    r = (sb.table("user_calibration_notes").select("notes, updated_at")
           .eq("project_id", project_id).eq("user_id", user_id).limit(1).execute())
    updated = None
    if r.data:
        mine = (r.data[0].get("notes") or "").strip()
        updated = r.data[0].get("updated_at")

    n_edits = 0
    try:
        n_edits = (sb.table("style_edits").select("id", count="exact")
                     .eq("project_id", project_id).eq("user_id", user_id)
                     .limit(1).execute()).count or 0
    except Exception:
        logger.exception("count style_edits failed")

    n_pos = len(_fetch_labeled(sb, project_id, "positive", user_id))
    n_neg = len(_fetch_labeled(sb, project_id, "negative", user_id))

    return {
        "project_id": project_id,
        "shared_calibration": shared,
        "my_calibration": mine,
        "my_calibration_updated_at": updated,
        "edits_fed": n_edits,
        "my_positive_examples": n_pos,
        "my_negative_examples": n_neg,
    }


def set_my_style(sb, project_id: str, *, user_id: str, notes: str) -> dict:
    """手动改写我的调校笔记(蒸馏结果不满意时直接改)。"""
    (sb.table("user_calibration_notes")
       .upsert({"project_id": project_id, "user_id": user_id, "notes": notes.strip()},
               on_conflict="project_id,user_id").execute())
    return {"project_id": project_id, "notes": notes.strip()}
