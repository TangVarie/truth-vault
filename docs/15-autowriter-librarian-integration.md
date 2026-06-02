# docs/15 · autowriter 接入"飞轮馆员"接入说明(R-032)

**面向**: autowriter 仓的维护者。
**目标**: 让 autowriter 写稿时,向 TV 的 **LLM 馆员服务**借阅匹配的"真实爆款经验",注入 system prompt —— 即 pull 模型(D-038 / [docs/14](14-channel2-pull-librarian.md))的消费侧。
**背景**: 通道2 已从 push(TV 预先把爆款塞进 `autowriter.items`)改为 pull(TV 当图书馆,aw 写稿时按 brief 来借)。TV 侧已全部建好 + 馆员服务**已上线 Railway**。aw 这边要做的就一件:**调一次 HTTP + 把返回注入 prompt**。

---

## 0. 馆员服务契约(TV 侧已交付、已上线)

```
POST  {LIBRARIAN_URL}/librarian
  header:  X-Librarian-Key: <内部 key>
  body (brief, JSON):
    { "consumer": "autowriter",
      "project_id":  "<aw 项目 id/名>",
      # —— 项目级稳定字段(馆员会 prompt-cache 这部分)——
      "brand": "...", "project_name": "...",
      "system_prompt": "...", "system_prompt_tone": "...",
      "system_prompt_exec": "...", "tactics": "...", "calibration_notes": "...",
      # —— 本次 batch 的 delta ——
      "tactic": "...", "target_audience": "...", "tone": "...",
      "extra_instructions": "...", "draft_topic": "..."(可选) }

→ 200  { "selected": [
    { "source_note_id": "...", "why_relevant": "...", "borrow_what": "...",
      "tier": "爆|大爆|参考", "hook_type": "...", "structure": "...",
      "why_it_worked": "...", "transferable_tactic": "...", "excerpt": "..." }, ...(0-5 条) ] }
```

- **空库 / 馆员内部出错 → `{"selected": []}`**(不是 500)。所以 aw 永远拿得到一个可用结构,`[]` 就当"这次没飞轮料"处理。
- `GET {LIBRARIAN_URL}/health` → `{"ok":true}`(健康检查)。
- 鉴权:没带对 `X-Librarian-Key` → 401。

> URL 和 key 由 TV 侧给你(部署在 Railway)。馆员服务内部已做:结果缓存 + Anthropic prompt caching + 走帆谷中转站。aw 不用关心这些,只管发 brief、收 selected。

---

## 1. config.py:加两个配置(沿用现有 `_get_secret`)

```python
# ── Flywheel librarian (TV pull 馆员) ────────────────────────────────────
# 留空 = 不接飞轮(写稿照常,只是没有"真实爆款参照"这一节)。
LIBRARIAN_URL: str = _get_secret("LIBRARIAN_URL")       # 例 https://truth-vault-production.up.railway.app
LIBRARIAN_API_KEY: str = _get_secret("LIBRARIAN_API_KEY")
LIBRARIAN_TIMEOUT_SEC: float = float(_get_secret("LIBRARIAN_TIMEOUT_SEC") or "8")
```

---

## 2. 一个馆员客户端(放 `clients.py` 或新建 `librarian_client.py`)

```python
import httpx, config
from logger_utils import mask_secrets  # 你仓已有

def fetch_flywheel_lessons(brief: dict) -> list[dict]:
    """向 TV 馆员借阅经验卡。任何异常/超时/未配 → 返回 [](绝不阻塞写稿)。"""
    if not config.LIBRARIAN_URL or not config.LIBRARIAN_API_KEY:
        return []                              # 没接飞轮, 静默跳过
    try:
        resp = httpx.post(
            f"{config.LIBRARIAN_URL.rstrip('/')}/librarian",
            headers={"X-Librarian-Key": config.LIBRARIAN_API_KEY},
            json=brief,
            timeout=config.LIBRARIAN_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        sel = resp.json().get("selected")
        return sel if isinstance(sel, list) else []
    except Exception as exc:                    # 超时/网络/4xx/5xx 全吞
        # 飞轮是增强项, 不是写稿前置依赖 —— 失败就当没有, 用 owner 自有正例照常写。
        import logging; logging.getLogger("autowriter").warning(
            "flywheel librarian unavailable, skipping (%s)", mask_secrets(str(exc)))
        return []
```

> 用同步 `httpx.post` 即可(generate_batch 本就在 worker 线程里同步跑)。

---

## 3. generate_batch:调一次 + 透传

`generator.py:generate_batch(...)` 里,在你已经拿到 `project` + 本次 batch 参数(tactic / target_audience / tone / extra_instructions)、且准备调 `memory.build_layered_system_prompt(...)` **之前**:

```python
from librarian_client import fetch_flywheel_lessons   # 或 clients.fetch_flywheel_lessons

brief = {
    "consumer": "autowriter",
    "project_id": project["id"],
    "brand": project.get("brand"),
    "project_name": project.get("name"),
    "system_prompt": project.get("system_prompt"),
    "system_prompt_tone": project.get("system_prompt_tone"),
    "system_prompt_exec": project.get("system_prompt_exec"),
    "tactics": project.get("tactics"),
    "calibration_notes": project.get("calibration_notes"),
    "tactic": tactic,                       # 本次 batch 的
    "target_audience": target_audience,
    "tone": tone,
    "extra_instructions": extra_instructions,
    # "draft_topic": <如有本次选题/主题, 填上更准>
}
flywheel_lessons = fetch_flywheel_lessons(brief)        # [] 时下面那节自动不出现
```

把 `flywheel_lessons` 透传给 `build_layered_system_prompt(...)`(下一步给它加形参)。

---

## 4. build_layered_system_prompt:加一节(注入 **P2 会话层、不缓存**)

`memory.py:build_layered_system_prompt(...)` 已有 Layer 4 (P1) 注入 owner 的 `positive_examples`(`[优质正案例 ...]`)。**飞轮经验跟它是两回事**(owner 主观正例 vs 现实爆款客观经验),且**按本次 brief 变化**——所以:

- **给函数加形参** `flywheel_lessons: Optional[list[dict]] = None`。
- **注入到 P2(会话层、`cache_control` 不缓存)**,不要放进缓存的 P1 —— 因为 selected 随 brief(tactic/选题)每批变,放进缓存层会把你的 prompt cache 每批打穿。(馆员服务自己已经把 LLM 结果缓存了,这里只是 aw 侧的 prompt-cache 卫生。)

P2 段里加(形状参考现有 `[优质正案例]`):

```python
if flywheel_lessons:
    blocks = []
    for L in flywheel_lessons[:5]:
        blocks.append(
            f"· 钩子：{L.get('hook_type') or '?'}｜为何有效：{L.get('why_it_worked') or ''}\n"
            f"  借这条的：{L.get('borrow_what') or ''}（相关性：{L.get('why_relevant') or ''}）\n"
            f"  原文片段：{(L.get('excerpt') or '')[:200]}"
        )
    p2_sections.append(
        "[真实爆款参照 · 系统按本次选题从帆谷飞轮库匹配]\n"
        "下面是现实中真爆过 / 运营确认值得参考的帆谷笔记的提炼经验。"
        "借鉴其钩子 / 结构 / 手法与角度,**严禁照抄原文的标题主干或具体句子**。\n"
        + "\n\n".join(blocks)
    )
```

> 与 owner 的 `[优质正案例]` 并列、分区标注 —— 两套都进 prompt,互不替代(docs/14 §1 的"owner 判断 ⊕ 飞轮内容")。

---

## 5. 不要动的东西

- autowriter 原生 `items.example_label`(owner 在 Memory Manager 手标的正/负例)+ `build_system_prompt` 对它的消费 —— **完全不动**。飞轮是**新增并列**的一节,不替代 owner 自有正例。
- negative 反向通道(`example_label_proposal` → Memory Manager review)—— 不动。
- 旧的"TV push 进 items"那条 —— TV 侧已停(`external_source` 那套),aw 不用管;**别再依赖 `items` 里出现 TV 来源的 positive**。

---

## 6. 降级语义(重要)

- 未配 `LIBRARIAN_URL/KEY` / 馆员超时 / 返回 `[]` / 任何异常 → `flywheel_lessons = []` → P2 那节不出现 → **写稿照常(用 owner 自有正例)**。飞轮**永远不是**写稿的前置依赖。
- 现在 TV 书架是空的(还没有真·非 synthetic 爆款),所以**初期 selected 基本都是 `[]`**,接好了也"看不到效果"是正常的;等运营在飞书标真爆款 + TV 策展 pass 跑过,才会开始返回经验。先把管子接通即可。

---

## 7. 自测

```bash
# 馆员在不在
curl -s {LIBRARIAN_URL}/health           # {"ok":true,...}
# 发个 brief(带 key)
curl -s -X POST {LIBRARIAN_URL}/librarian -H "X-Librarian-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"consumer":"autowriter","project_id":"x","brand":"waytogo","tactic":"经期场景","target_audience":"经期人群"}'
# 现在期望 {"selected":[]}(空库)。接好后, 跑一个真 batch, 看 P2 是否在有料时出现该节。
```

**工时估计**: 0.5–1 天(一个 HTTP client + generate_batch 透传 + build_layered_system_prompt 加一节 + config + 自测)。**owner**: autowriter 维护者。**前置**: 无(TV 侧 + 服务已就绪;空库期间接好也只是 no-op,不影响现有写稿)。
