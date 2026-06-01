# docs/13 · 飞轮启动 Runbook（WTG_phase1 实操）

**新增**: 2026-05-29 (Session #14)
**适用**: 基础设施已就绪、ingest 已生效，但下游两条通道一条都没流动时（连库实测的真实状态）。

---

## 0. 为什么需要这份文档

2026-05-29 连生产库（`kduysqedrclrfevrxiie`）核对的地面真相：

- `truth_vault.notes` 已有 **682 行**（ingest 通了，ClientOptions 修复生效）。
- 但**只 onboard 了 `WTG_phase1`（waytogo 个护洗护）一个项目**；tier 分布
  `趴 658 / 风控 19 / 未知 3 / 预备 1 / 爆 1 / 大爆 0 / 参考 0`。
- **下游同步全 0**：`synced_to_ssll=0`、`synced_to_aw=0`，`public.reference_samples`
  与 `autowriter.items` 里来自 TV 的行都是 0。

飞轮空转有**两个各自独立、且代码都没错**的原因：

1. 唯一那条「爆」的 `tier_source=数值推断`，两条通道**按设计都排除数值推断**
   （只信任人工确认的 tier，"爆款是人的判断，不只是数字"）。
2. `WTG_phase1` 的 `mapping_to_autowriter_project_id` / `mapping_to_sanshengliubu_project_id`
   **都没配**，autowriter 注入候选 view 硬要求 aw 映射非空 → 产出 0 候选。

所以**启动飞轮的工作是运营 onboarding，不是改代码**。下面是把 WTG 飞轮真正转起来
的操作清单。

---

## 1. 飞轮资格条件（两条通道各自的硬性 filter）

理解这些，就知道为什么某条笔记进 / 不进飞轮。

### 通道 1 · TV → `public.reference_samples`（ssll 参照库）
脚本 `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py`，filter：
- `tier ∈ ('爆','大爆','参考')`
- `tier_source != '数值推断'`（只认人工确认的 tier）
- `data_quality_flags.synthetic != true`（排除伪爆贴）
- **不需要** `mapping_to_sanshengliubu_project_id`：按 `projects.category` + `platform`
  写入，ssll 用 category/platform 检索。映射列仅作溯源，可不配。
- ⚠ 前提：`projects.category` / `platform` 要对（`ensure_project_exists` 从 yaml 填，
  默认 category=其他 / platform=xiaohongshu）。category 错会让 ssll 退化到 platform-only 检索。

### 通道 2 · TV → `autowriter.items`（example_label='positive' 注入）
脚本 `scripts/sync_truth_vault_baokuan_to_autowriter_items.py`，候选由
`truth_vault.v_autowriter_injection_candidates` view 决定，filter：
- `tier ∈ ('爆','大爆','参考')`
- `tier_source != '数值推断'`
- `publish_time` 在近 12 个月内
- `data_quality_flags.synthetic != true`
- **`mapping_to_autowriter_project_id IS NOT NULL`**（必须配，且指向真实 aw 项目）
- 且该 aw 项目 `autowriter.projects.owner_id` 非空（脚本用它做 items.user_id 以满足 RLS）。

权重（`injection_score`，决定注入排序）：大爆 +0.5 / 爆 +0.3 / **参考 +0.15**（低权重）。

---

## 2. Step 1 · 让 WTG 有"合格爆款"

WTG 是个护洗护，天然少爆贴（658/682 是趴）——这正是 2026-05-27 加「参考」tier 的初衷。
两条路径（任选，可并用）：

### 路径 A（推荐，常态）· 运营在飞书标注
在飞书「流量状态」列，给值得进飞轮的笔记填 **爆贴 / 大爆 / 参考**（WTG yaml 已配「参考」
规则，见 `mappings/WTG_phase1.yaml`）。然后重跑 ingest：

```bash
cd scripts
python sync_feishu_notes_to_truth_vault.py WTG_phase1            # 或加 --dry-run 先看
```

这样 tier 来自状态字段（`tier_source=状态字段`），是人工确认的，能进两条通道。

### 路径 B（一次性，⚠️ 不持久，见下方警告）· 把已有数值推断爆款转人工确认
如果某条 `数值推断` 的爆款，运营复核后确实算数，可把 `tier_source` 提成 `人工补录`
（`人工补录` 是 schema 合法 tier_source、权重 0.2）。先用质量复核 view 找候选：

```sql
-- 哪些笔记的人工标 tier 与互动量推断矛盾，或哪条数值推断爆款值得转人工
SELECT note_id, marked_tier, numeric_implied_tier, tier_source, interactions, discrepancy_type
FROM truth_vault.v_tier_discrepancy WHERE project_id = 'WTG_phase1';

-- 复核确认后，把指定笔记转成人工确认（示例）
UPDATE truth_vault.notes
SET tier = '爆', tier_source = '人工补录'
WHERE note_id = 'WTG_phase1_recvjACT8ep3bt';   -- 换成实际 note_id
```

> ⚠️ **路径 B 不持久**：这条 `UPDATE` 只改了 DB 当前行；**下次该项目飞书回灌
> （`sync_feishu_notes_to_truth_vault.py`）会按源头重算并覆盖 `tier_source`**，把它打回
> `数值推断`，笔记又被挡在闸外。2026-06-01 实测：手改 `人工补录` → ssll dry-run 能进 →
> 真跑时 ingest 先跑、把它冲回 `数值推断` → ssll `Found 0`，什么都没同步。
> 故路径 B 仅在「改完后不再回灌、或紧接着单独跑 ssll/aw sync」时有效；**要持久就走路径 A
> 在飞书源头标 tier**（`tier_source=状态字段`，回灌也不变）。当前 ingest 不把 `人工补录`
> 当 sticky override（要让路径 B 真正可靠，需给 ingest 加"保留人工 override"逻辑，尚未实现）。

> 不要无脑把所有数值推断爆款转人工——那等于绕过"人工确认"这道闸。只转复核过的。

---

## 3. Step 2 · 配跨系统映射

### 通道 2（autowriter）必配
`mapping_to_autowriter_project_id` 要指向一个**真实存在、owner_id 非空**的 autowriter 项目。
先在 autowriter 找到目标项目 id：

```sql
-- 在 autowriter 里挑一个对应 waytogo 个护洗护的项目（或先在 autowriter 建一个）
SELECT id, name, owner_id FROM autowriter.projects ORDER BY created_at DESC;
```

然后回写 TV 的项目映射：

```sql
UPDATE truth_vault.projects
SET mapping_to_autowriter_project_id = '<上面选出的 autowriter 项目 UUID>'
WHERE project_id = 'WTG_phase1';
```

> `ensure_project_exists` 故意不覆盖这两个映射列（手工维护），所以重跑 feishu sync 不会清掉。

### 通道 1（ssll）可选
`sync_truth_vault_baokuan_to_sanshengliubu.py` 不读 `mapping_to_sanshengliubu_project_id`，
只按 category/platform 写。配它仅为溯源好看：

```sql
UPDATE truth_vault.projects
SET mapping_to_sanshengliubu_project_id = '<ssll 项目标识，可选>'
WHERE project_id = 'WTG_phase1';
```

---

## 4. Step 3 · 手动跑两条通道 + 验证

先 dry-run 看候选顺不顺眼，再真跑：

```bash
cd scripts
# 注入候选预览（不写库）
python preview_injection_candidates.py --project WTG_phase1

# 通道 1：TV → ssll reference_samples
python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run
python sync_truth_vault_baokuan_to_sanshengliubu.py

# 通道 2：TV → autowriter items
python sync_truth_vault_baokuan_to_autowriter_items.py --dry-run
python sync_truth_vault_baokuan_to_autowriter_items.py
```

验证下游真的有数据了（这些查询就是 Session #14 连库用的）：

```sql
-- 飞轮状态总览（含参考级独立计数）
SELECT project_id, total_baokuan, synced_to_ssll, pending_ssll_sync,
       synced_to_aw, pending_aw_sync, total_reference
FROM truth_vault.v_flywheel_sync_status WHERE project_id = 'WTG_phase1';

-- 下游确有 TV 来源行
SELECT count(*) FROM public.reference_samples WHERE source_truth_vault_note_id IS NOT NULL;
SELECT count(*) FROM autowriter.items WHERE external_source = 'truth_vault';

-- 注入候选 view 现在应 > 0
SELECT count(*) FROM truth_vault.v_autowriter_injection_candidates;
```

**预期**：`pending_*_sync` 下降、`synced_*` 上升、两个 count(*) > 0。
若 `v_autowriter_injection_candidates` 仍为 0，按 §1 通道 2 的 filter 逐条排查
（多半是 tier_source 还是数值推断，或 aw 映射没配 / 指向的 aw 项目不存在）。

---

## 5. Step 4 · 开 cron（最后一步）

确认手动 sync 跑通、下游有数据后，再启用每日自动同步：

1. 配齐 GitHub Secrets（`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` /
   `FEISHU_APP_ID` / `FEISHU_APP_SECRET`；`ANTHROPIC_API_KEY` 可选用于 essence 标注）。
2. 在 `.github/workflows/daily-sync.yml` 顶部把 `schedule:` 那段取消注释。
3. 先手动 `Run workflow`（dry_run=true）跑一遍确认全绿。

> daily-sync 的失败聚合已就位：任一 sync 步骤失败 → workflow 退出非零 → GitHub 给
> repo owner 发邮件，不会再静默漂移。

---

## 6. 一句话总结

代码和集成契约都没问题，飞轮没转纯粹是因为 **WTG 还没有人工确认的爆款 + autowriter
映射没配**。Step 1（标参考/确认 tier）+ Step 2（配 aw 映射）+ Step 3（手动 sync 验证）
做完，飞轮就转起来了；稳定后再 Step 4 开 cron。
