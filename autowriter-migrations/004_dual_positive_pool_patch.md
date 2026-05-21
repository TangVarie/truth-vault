# 004 · autowriter 双池 positive examples (TV-synced vs native) 集成 patch

> ⚠️ 这不是 SQL migration, 是给 autowriter 仓库自身的代码 patch 说明.
> autowriter 在独立仓库, 不能从这边直接改. 这份文件描述要改 autowriter 的
> 哪几行, 由 autowriter 维护者参考施工.

## 触发背景

来自 truth-vault `CURRENT_STATE.md` 延后清单 🟡 慢性病 #8:

> **autowriter 端拆 "TV positive" vs "native positive" 双池**
> 触发条件: autowriter 运营反馈"内置的 positive 永远轮不上",
> 或想做 A/B 对比 TV-injected vs native 的下游表现.

## 当前问题

`autowriter.db.list_example_items(client, project_id, label='positive', limit=5)`
当前混在一起按 `created_at DESC` 排:

- TV daily sync 每天往 autowriter.items 写最多 5 条 TV-positive
  (external_source='truth_vault')
- 运营在 autowriter UI 里手动标的 native positive
  (external_source IS NULL) — 通常更稀有, 一周才 1-2 条
- list_example_items 拉 limit=5 时, TV 的高 created_at 几乎稳吃 5 个 slot,
  native 的 positive 实际**永远轮不上** build_system_prompt.

下游 build_system_prompt(positive_examples=...) 收到的只有 TV-injected 的,
看不见运营 manual 挑选的 vibe.

## 改动方案 (最小侵入)

给 `list_example_items` 加一个可选 `source_filter` 参数, 不打破现有调用方.

### autowriter/db.py · list_example_items 签名

```python
def list_example_items(
    _client: Client,
    project_id: str,
    label: str,
    limit: int = 5,
    source_filter: str | None = None,  # NEW: 'truth_vault' / 'native' / None=both (default behavior unchanged)
) -> list[dict]:
    """Return recent items marked with the given label.

    source_filter:
        None (default)  — both TV-synced + native, ordered by created_at DESC.
                          Preserves existing caller behavior.
        'truth_vault'   — only items with external_source = 'truth_vault'.
        'native'        — only items with external_source IS NULL
                          (i.e. autowriter operator-tagged).
    """
    batches = list_batches(_client, project_id, limit=50)
    if not batches:
        return []
    batch_ids = [b["id"] for b in batches]

    q = (
        _client.table("items")
        .select("id, best_version_id, external_source, versions(id, title, body, version_num)")
        .in_("batch_id", batch_ids)
        .eq("example_label", label)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if source_filter == "truth_vault":
        q = q.eq("external_source", "truth_vault")
    elif source_filter == "native":
        q = q.is_("external_source", "null")
    # source_filter == None: no extra filter; preserve old behavior
    res = q.execute()

    # ... rest of function unchanged
```

### autowriter/app.py (or wherever build_system_prompt is called)

```python
# Old:
# pos_examples = db.list_example_items(client, project_id, "positive", limit=5)

# New: mix TV-synced + native explicitly (default 3 TV + 2 native if both available)
pos_native = db.list_example_items(client, project_id, "positive", limit=2, source_filter="native")
pos_tv     = db.list_example_items(client, project_id, "positive", limit=3, source_filter="truth_vault")
# Native goes first so build_system_prompt's [:5] slice doesn't drop them
# under heavy TV inflow.
pos_examples = pos_native + pos_tv

full_system_prompt = mem_module.build_system_prompt(
    # ... other args ...
    positive_examples=pos_examples or None,
    # ... 
)
```

## 比例的选择 (3 TV + 2 native) 怎么定

| 项目阶段 | 建议 native:TV 比例 | 理由 |
|---|---|---|
| 刚 onboarding, native 还没数据 | 0:5 | TV 历史爆款是唯一信号 |
| native 有 ≥ 5 条 | 2:3 | TV 是大基础, native 是 "运营当前想强调的 vibe" 信号 |
| native ≥ 10 + 项目稳定运行 3 个月+ | 3:2 | native 已经反映了运营对当前阶段的判断, 应该领导 |

数字写死在 app.py 里就行, 不用做成参数. 改起来 1 行.

## 验证 patch 之后的行为

1. 跑 `python autowriter/db.py` (或对应的 unit test) 确认 list_example_items
   接受新签名后老调用方依然 work (默认 source_filter=None 保留旧行为).
2. 在 autowriter 开发环境跑一次 build_system_prompt, 确认 P1 段里能看到
   既有 TV-injected 的样本也有运营 native 的样本 (用项目里至少 1 条
   native positive 的项目测).
3. truth-vault 端 `python scripts/check_positive_saturation.py` 也跟着
   一起跑, 看 dominant_lever_ratio 有没有掉下来 (理论上 native 引入的
   多样性会让单一 lever 的占比下降).

## 不需要做的

- 不要在 autowriter 这边加新表 — 一切信息已经在 items.external_source 里
- 不要新加 schema migration — migration 002 已经加了 external_source
  列和 partial UNIQUE INDEX
- 不要改 truth-vault 这边的 sync 脚本 — TV 的写入逻辑不变, 改的是 autowriter
  的读取逻辑

## 部署顺序

1. autowriter 仓库改 db.py + app.py, 跑测试, 部署
2. (无需 truth-vault 这边改任何东西; 这是单纯的 autowriter 内部 refactor)
3. 部署后 1 周后跑 check_positive_saturation.py 观察 dominant_lever_ratio
   是否如预期下降
