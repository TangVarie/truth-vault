# autowriter 接馆员 · 快速接入(照着做)+ 自测 curl

> 给 **autowriter 维护者**:把"写稿时向飞轮馆员借经验卡"接上(R-032)。
> 这是飞轮的**最后一公里** —— TV 侧已把爆款策展成经验卡放上馆员书架(`v_flywheel_lesson_cards`),
> 就差 aw 写稿时调一下馆员、把卡注入 prompt。
> 设计/背景见 [docs/14](14-channel2-pull-librarian.md)(为什么 pull)/ [docs/15](15-autowriter-librarian-integration.md)(详细契约+落地反馈);本文是**可照做的精简版**。
>
> ✅ 状态(2026-06-04 更新):**autowriter 已实现 R-032** —— `librarian_client.py`(`build_brief` + `fetch_flywheel_lessons`,
> fail-open)+ `app.py` 两处调用(单条 + 批量生成)+ `memory.build_layered_system_prompt` 把卡注入 **P2 层(不缓存)**,
> 注的正是 `structure` / `transferable_tactic` / `borrow_what` / `why_relevant`,与本文契约一致。
> 曾因 **librarian 的模型 env 没设对**而返回 `[]`(见 §6 故障排查),修好后端到端可通。本文现作**契约参考 + 自测手段 + 故障排查**。

---

## 0. 前置(找 TV/运维拿两样)

| 要的东西 | 说明 |
|---|---|
| `LIBRARIAN_URL` | Railway 上 librarian 服务的公网地址(如 `https://tv-librarian-production.up.railway.app`)。**不是** worker、不是 onboarder |
| `LIBRARIAN_API_KEY` | 调馆员的口令(对应 librarian 服务的 `LIBRARIAN_API_KEY` env)。请求带 header `X-Librarian-Key` |

> 馆员**只收 brief、只回 selected**;Supabase service_role 等机密都在服务端,**绝不下发给 aw**。aw 不需要任何 DB 凭证。

---

## 1. 先自测(不写一行代码,证明馆员端能用)

```bash
export LIBRARIAN_URL='https://<你的-librarian>.up.railway.app'
export LIBRARIAN_API_KEY='<librarian 口令>'

curl -sS -X POST "$LIBRARIAN_URL/librarian" \
  -H "X-Librarian-Key: $LIBRARIAN_API_KEY" \
  -H 'content-type: application/json' \
  -d '{
    "consumer": "autowriter",
    "project_id": "WTG-test",
    "brand": "waytogo",
    "system_prompt": "为 waytogo 一次性内裤写小红书种草,强调便携卫生、差旅/经期场景。",
    "tactic": "经期场景痛点切入",
    "target_audience": "20-35 岁女性,经期/差旅人群",
    "draft_topic": "经期出差怎么解决内裤换洗尴尬"
  }' | jq
```

**预期**(书架现有 1 张 WTG 卡,应被选中):
```json
{
  "selected": [
    {
      "source_note_id": "WTG_phase1_recvk9VPCTNG1b",
      "why_relevant": "同品牌同人群的经期场景爆款…",
      "borrow_what": "开头钩子/评论区设计…",
      "tier": "参考",
      "synthetic": true,
      "hook_type": "…", "structure": "…",
      "why_it_worked": "…", "transferable_tactic": "…",
      "excerpt": "【标题】…"
    }
  ]
}
```
- 拿到非空 `selected` = **馆员端跑通**,可以接代码了。
- 拿到 `{"selected": []}` 也**正常**:可能书架对该 brief 没合适卡(库还小)。接好后随库长大自然有料。
- `401` = key 不对;`400` = body 不是 JSON object。

---

## 2. 契约(精确,对应 `librarian/app.py` + `core.py`)

**请求** `POST {LIBRARIAN_URL}/librarian`,header `X-Librarian-Key: <key>`,body = brief(JSON object):

| 字段 | 必填 | 用途 |
|---|---|---|
| `consumer` | ✓ | 固定 `"autowriter"`(进缓存 key + 审计) |
| `project_id` | ✓ | 你侧项目标识(进缓存 key) |
| `brand` / `project_name` / `system_prompt` / `system_prompt_tone` / `system_prompt_exec` / `tactics` / `calibration_notes` | 选 | **项目级稳定字段** → 进【缓存】system 块(同项目跨请求复用,省钱) |
| `tactic` / `key_messages` / `target_audience` / `tone` / `extra_instructions` / `draft_topic` | 选 | **本次 delta** → 每次变,馆员据此挑卡 |

> 字段都给上越准越好,但**全是可选**(除 consumer/project_id);馆员按你给的做相关性推理(同品牌/品类/人群优先,也会跨主题借可迁移手法)。

**响应** `200 {"selected": [ ... ]}`,每个元素:

| 字段 | 含义 | 是否注入 prompt |
|---|---|---|
| `why_relevant` | 为什么对这次写作有用 | 可注 |
| `borrow_what` | 借它哪个部位 | 可注 |
| `hook_type` / `structure` / `why_it_worked` / `transferable_tactic` | 经验卡核心(钩子/结构/为何有效/可迁移手法) | **建议注入** |
| `excerpt` | 原帖片段 | 可注(截断) |
| `tier` | 爆/大爆/参考 | 内部用 |
| `synthetic` | `true`=指标未验证(伪爆贴) | **注入时加"⚠️指标未验证、只借内容"** |
| `source_note_id` | 来源 id | **不要注入**(对模型是噪音) |

**降级铁律**:馆员空库/出错一律回 `200 {"selected": []}`,**绝不抛 500 阻塞写稿**。aw 侧也照此:超时/非 200/异常 → 当"这次没飞轮料"、用自有正例照常写。

---

## 3. 接入代码(Python 示例,~30 行)

```python
import os, httpx

LIBRARIAN_URL = os.environ.get("LIBRARIAN_URL")
LIBRARIAN_API_KEY = os.environ.get("LIBRARIAN_API_KEY")

def fetch_flywheel_cards(brief: dict, timeout: float = 8.0) -> list[dict]:
    """写稿前向馆员借经验卡。任何异常/超时/空/非200 → 返回 [](降级到 owner 自有正例,绝不阻塞写稿)。"""
    if not LIBRARIAN_URL:
        return []
    try:
        r = httpx.post(
            f"{LIBRARIAN_URL.rstrip('/')}/librarian",
            headers={"X-Librarian-Key": LIBRARIAN_API_KEY or "", "content-type": "application/json"},
            json=brief, timeout=timeout,
        )
        return (r.json() or {}).get("selected") or [] if r.status_code == 200 else []
    except Exception:
        return []

def build_flywheel_block(cards: list[dict]) -> str:
    if not cards:
        return ""
    lines = []
    for c in cards:
        tag = "（⚠️指标未验证,只借内容层面）" if c.get("synthetic") else ""
        lines.append(
            f"- 钩子:{c.get('hook_type')}｜结构:{c.get('structure')}｜可借手法:{c.get('transferable_tactic')}{tag}\n"
            f"  为何有效:{c.get('why_it_worked')}\n"
            f"  片段:{(c.get('excerpt') or '')[:200]}"
        )
    return "【飞轮·历史爆款可借鉴(与下面自有正例并列参考)】\n" + "\n".join(lines)
```

**怎么拼 brief + 注哪儿**:

```python
brief = {
    "consumer": "autowriter",
    "project_id": project.key,                 # 你侧项目标识
    "brand": project.brand,
    "project_name": project.name,
    "system_prompt": project.system_prompt,
    # 本次 delta(有就给):
    "tactic": batch.tactic,
    "key_messages": batch.key_messages,
    "target_audience": batch.target_audience,
    "draft_topic": batch.topic,
}
flywheel_block = build_flywheel_block(fetch_flywheel_cards(brief))
```

注入位置(关键,见 docs/15 §4):
- 放进 **P2 会话层(不缓存)**,**不要**放进缓存的 P1 —— selected 随每批 brief 变,塞进缓存层会把 aw 自己的 prompt cache **每批打穿**。
- 与 owner **自有正例并列、分区**(增强项,不替代 owner 判断)。
- 注入 `structure` + `transferable_tactic`(+ 钩子/为何有效/片段);**不注入 `source_note_id`**。

**配置**:aw 侧加 env `LIBRARIAN_URL` + `LIBRARIAN_API_KEY`(= librarian 服务的那把)。建议超时 5-10s、fail-open。

---

## 4. 验收(怎么确认"真接通了")

1. **自测 curl(§1)返回非空 / 200** —— 馆员端 OK。
2. **aw 真生成一次**后,查 TV 库:
   ```sql
   select count(*) from truth_vault.flywheel_librarian_cache;   -- 应 > 0(之前是 0)
   ```
   `flywheel_librarian_cache` 出现行 = aw 真的调到了馆员(每个不同 brief 一行,带 consumer='autowriter')。**这一条从 0→正,就是飞轮借阅端正式跑通的硬证据。**
3. aw 生成的 prompt 里能看到"【飞轮·历史爆款可借鉴】"那段(有料时)。

---

## 5. 常见问题

- **selected 老是空**:书架现在只有 1 张卡(WTG 参考)。随运营在飞书标更多真爆款 + daily-sync 策展,卡会变多;跨品牌也能借到可迁移手法。先把管子接通,别等库满。
- **会不会拖慢写稿**:不会。fail-open + 超时降级;且馆员有**结果缓存 + prompt 缓存**,同库同 brief 几乎零成本。
- **要不要 ssll 也接**:可选(R-033),同契约;ssll 现有 `retrieve_reference_packs` 也可不动,只是少借一路飞轮料。

---

## 6. 故障排查

### 自测 curl / 真跑都返回 `{"selected":[]}`,且 `flywheel_librarian_cache` 一直 0

**最常见:librarian 的模型 env 没设对(2026-06-04 实锤)。** 三个 Railway 服务的"模型" env **变量名各不相同**:

| 服务 | 模型 env 变量名 | 默认 |
|---|---|---|
| worker | `ESSENCE_MODEL` | `claude-sonnet-4-6` |
| **librarian** | **`FLYWHEEL_LIBRARIAN_MODEL`** | `claude-sonnet-4-6` |
| autowriter | `CLAUDE_MODEL` | `claude-sonnet-4-6` |

如果你的中转站通道**不 serve 默认的 `claude-sonnet-4-6`**(于是你给 worker/aw 设了别的能跑通的模型),
却**忘了给 librarian 设 `FLYWHEEL_LIBRARIAN_MODEL`** → 馆员每次 LLM 调用都失败、`except` 降级成 `[]`。
从外面看是 `200 {"selected":[]}`(看不出错),`flywheel_librarian_cache` 也因没成功而留 **0**。

**修:在 librarian 服务把 `FLYWHEEL_LIBRARIAN_MODEL` 设成你通道认的模型**(= worker 的 `ESSENCE_MODEL` / aw 的 `CLAUDE_MODEL`)→ 重部署 → 重跑自测,`selected` 出卡、`flywheel_librarian_cache` 0→1。

> 想确认是不是它:看 librarian 服务的 **Railway Logs**,会有 `librarian_select LLM 选取失败` + 真错误
> (典型 `no available channel for model ... under group ...` = 模型名不对)。

### 其它
- `401` → `X-Librarian-Key` 与 librarian 的 `LIBRARIAN_API_KEY` 不一致。
- 模型/通道都对但仍空 → 书架暂无匹配的卡(库小时正常);先把管子接通,别等库满。
