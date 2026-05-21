# 005 · autowriter Memory Manager UI · 负例审核 tab 集成 spec

> ⚠️ 这不是 SQL migration, 是给 autowriter Streamlit UI 的功能 spec.
> autowriter 在独立仓库, 这份文件描述要在 autowriter UI 里加什么, 由
> autowriter 维护者参考实现.

## 触发背景

来自 truth-vault `CURRENT_STATE.md` 延后清单 🟡 慢性病 #8 (negative 审核):

> **autowriter Memory Manager UI 负例审核 tab**
> 候选写入了 `example_label_proposal` 但 autowriter 没前端审核界面 → 
> negative_examples pipeline 实际上没贯通.
> 触发条件: 决定要让 negative_examples 真注入到 build_system_prompt 时
> (不做这个, 负例反向通道整条链都是白搭).

## 现状

`truth-vault/scripts/extract_negative_examples_from_autowriter.py` 每月跑一
次, 扫 autowriter 历史 items 找 3 类 negative 信号:
- A · 用户手动重写过 AI 版 (强信号 `negative_manual_rewrite`)
- B · 用户反馈触发的迭代 (中信号 `negative_feedback_iter`)
- C · 同 batch 部分通过部分卡 needs_revision (弱信号 `negative_batch_rejected`)

把结果写到 `autowriter.items.example_label_proposal` 这个 NULLABLE 字段.
**autowriter 端只是落了数据, 运营在 UI 里没法 review, 没法批量确认转成
`example_label='negative'`**. 所以:

- `build_system_prompt(negative_examples=...)` 的 P1 段 "[反面案例 · 主动
  规避]" 实际上永远是空的
- 整条 negative 反向通道空跑

## 需要的 UI

在 autowriter Streamlit app 的 Memory Manager 页 (或者新加一个 page)
加一个 tab, 叫 **"负例候选 review"**.

### 显示

| 列 | 内容 | 备注 |
|---|---|---|
| Item ID (短) | `items.id` 前 8 字 | 链接到该 item 的详情页 |
| 项目 | 通过 `batches.project_id` 拿到 | |
| 候选来源 | `example_label_proposal` 字面值 ("negative_manual_rewrite" 等) | 用颜色区分 A/B/C 强中弱 |
| Best version 摘要 | `versions.title` (best_version_id) 前 60 字 | hover 看完整 body |
| 创建时间 | `items.created_at` | 倒序 |
| 操作 | [Confirm Negative] [Reject Proposal] | 见下方 |

### 操作

- **Confirm Negative** 按钮 → `UPDATE items SET example_label='negative', example_label_proposal=NULL WHERE id=...`
  - 该 item 从此进 `build_system_prompt(negative_examples=...)` 的注入池
- **Reject Proposal** 按钮 → `UPDATE items SET example_label_proposal=NULL WHERE id=...`
  - 候选被运营判定为误标, 清掉 proposal 字段, 该 item 永远不会再次出现
    在审核列表 (extract 脚本只标 IS NULL 的)
- **批量操作**: 多选 checkbox + "全部确认 / 全部拒绝" 按钮
- **筛选**: 按候选来源 (A/B/C) 过滤, 默认先看 A (最强信号)

### 不需要做的

- 不要让运营**新建** negative example (这是 extract 脚本的工作)
- 不要允许编辑 item.body (那是 versions 表里的内容, item 只是元数据)
- 不要做"暂存"状态 (要么 confirm 要么 reject; 不审就让 proposal 留着)

## 后端 SQL 需要的 query

```python
# 在 autowriter/db.py 里加:
def list_negative_proposals(client, project_id: str = None, limit: int = 50):
    """运营 review 用. 返回 example_label_proposal IS NOT NULL 且
    example_label IS NULL 的 items + best version 摘要."""
    q = (
        client.table("items")
        .select("id, batch_id, example_label_proposal, created_at, "
                "best_version_id, versions(title, body)")
        .not_.is_("example_label_proposal", None)
        .is_("example_label", None)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if project_id:
        q = q.eq("batches.project_id", project_id)
    return q.execute().data or []


def confirm_negative_proposal(client, item_id: str):
    client.table("items").update({
        "example_label": "negative",
        "example_label_proposal": None,
    }).eq("id", item_id).execute()


def reject_negative_proposal(client, item_id: str):
    client.table("items").update({
        "example_label_proposal": None,
    }).eq("id", item_id).execute()
```

## 跟 build_system_prompt 的对接

现有 `autowriter/memory.py:build_system_prompt(negative_examples=...)` 已经
有逻辑会把 negative 装进 P1 段 (autowriter/memory.py:213-220 左右):

```python
if negative_examples:
    ex_blocks = []
    for ex in negative_examples[:3]:
        body_preview = (ex.get("body") or "")[:120].split("\n")[0]
        ex_blocks.append(f"标题：{ex['title']}\n正文节选：{body_preview}")
    p1_sections.append(
        "[反面案例 · 主动规避]\n" + "\n\n".join(ex_blocks)
    )
```

**所以 UI 加完之后, 运营 confirm 几条 negative, 下一次 batch 跑 build_system_prompt
就自动看到 [反面案例 · 主动规避] 段了, 不用动 memory.py**.

调用方 (app.py 或对应) 需要加:
```python
neg_examples = db.list_example_items(client, project_id, "negative", limit=3)
full_system_prompt = mem_module.build_system_prompt(
    ...
    negative_examples=neg_examples or None,
    ...
)
```

## 部署顺序

1. autowriter 加 list_negative_proposals / confirm / reject 三个 db 函数
2. autowriter 加 Memory Manager 的"负例候选 review" tab UI
3. autowriter 在 app.py build_system_prompt 调用前拉一次 negative_examples
4. 部署后让运营审 1-2 周 backlog, 看 negative 注入对生成质量的实际影响
5. 视效果决定是否继续跑 extract 脚本 (cron 加进 daily-sync.yml 之类)

## 不需要 truth-vault 这边改任何东西

整个改动在 autowriter 端. truth-vault 这边的 `extract_negative_examples_from_autowriter.py`
已经在持续生成候选 (跑了没人审而已).
