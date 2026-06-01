# Truth Vault 飞轮 · 集成与进度快照 (一眼跟进)

> 更新: 2026-05-27 (Session #13)。
> 本文件 = "现在到哪了 / 各环节怎么配合 / 哪些设了哪些没设 / 还差什么" 的速查。
> 详细历史见 `CURRENT_STATE.md`;排查手册见 `docs/12`;sister-repo 跟进见 `docs/10`。

---

## 1. 整体链路 (各环节怎么配合)

```
飞书多维表  (运营填: 流量状态 / 笔记状态 / 方向 / 观众分析 / 互动量 ...)
   │   sync_feishu_notes_to_truth_vault.py   ← GitHub Actions「Daily TV sync」
   ▼
truth_vault.notes  (+ metric_snapshots / comments / undeclared_quarantine)
   │   共享 Supabase: kduysqedrclrfevrxiie (ROC数据飞轮, 新加坡)
   │
   ├── 通道1  sync_..._to_sanshengliubu.py  → public.reference_samples → 三省六部 vibe_rewriter 检索池
   ├── 通道2  sync_..._to_autowriter_items.py → autowriter.items (正例池) → 写作工作台注入
   └── 反向   sync_autowriter_decisions_to_prepublish.py → truth_vault.prepublish_evaluations
```

- **tier 来源**: 飞书「流量状态」→ `tier_extraction` 规则 → `notes.tier`(大爆/爆/参考/预备/趴/风控/未知/数据异常)。
- **进飞轮的**: `tier ∈ (爆, 大爆, 参考)`,排除 `tier_source=数值推断`(机器猜的);`synthetic=true`(伪爆/关注)只挡 `爆/大爆`,`参考` 放行(纯人工判断·与指标真假无关)。
- **爆款统计**(`total_baokuan`)只算 爆/大爆;**「参考」单独计数**,不污染爆款标准。这是监控/业务信号,不驱动自动逻辑。

---

## 2. 基础设施 (已就绪 ✅)

- ✅ 共享 Supabase `kduysqedrclrfevrxiie`: `truth_vault`(14 表)+ `autowriter` + `public`(ssll)三 schema 齐。
  - ⚠️ 账号下另有旧库 `vnbcytilakkxojhgzeqr`(**无 truth_vault**,D-024 迁移前的旧 autowriter 库)。两库都有 autowriter,**secret 别指错**(详见 `docs/12`)。
- ✅ GitHub Secrets:`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 已配,sync 实跑通过。
  - ⬜ `ANTHROPIC_API_KEY` **未配**(可选,仅 essence LLM 标注用,不影响主链路)。
- ✅ 「Daily TV sync」workflow:目前**仅手动触发**;cron 仍注释关闭。
- ✅ 主链路代码 bug 全修(`schema=None` / 方向字段 list / 批量提速)—— PR #20–23,已并入 main。

---

## 3. 各项目接入进度

| 项目 | 进 truth_vault | sync_config(飞书凭据) | tier_thresholds | →autowriter 映射 |
|---|---|---|---|---|
| **WTG_phase1** | ✅ 682 notes | ✅ 已填 | ✅ 30/100（待策略确认） | ❌ `aw_map=null` |
| NUC_phase1 | ❌ 未接入 | ❌ null | ✅ yaml 有 | ❌ |
| NRT_phase2 / NRT_phase3 | ❌ 未接入 | ❌ null | ✅ yaml 有 | ❌ |

> `truth_vault.projects` 目前**只有 WTG 一行**。其余项目 sync_config 是 null,飞书 sync 跑不起来,所以还没进库。

WTG 数据现状:682 notes(512 条自动解出 content_format),662 metric_snapshots,192 comments;真爆款 0(运营在「流量状态」标的都是无水花/风控/评估中),仅 1 条数值推断「爆」。

---

## 4. 飞轮两条输出通道 · 接线状态 ⭐

- **通道1 · ssll `reference_samples`**:✅ 脚本已接(**不依赖** per-project 映射,直接写 `public.reference_samples`)。
  - WTG 当前 0 条流入 —— 唯一的「爆」是数值推断,ssll 按设计排除;运营标出真爆贴/参考后即会流入。
  - 🔴 **R-022 未解**:三省六部 `vibe_rewriter.md` 还没把 `reference_samples` 真正拼进 prompt → 数据到了 ssll 库但 LLM 还没用(见 `docs/10 § R-022`)。**这是飞轮"转起来产生价值"的最后阻塞。**

- **通道2 · autowriter `items`**:⚠️ **尚未接线** —— WTG 的 `mapping_to_autowriter_project_id` 是 **null**,而注入视图 `v_autowriter_injection_candidates` 要求它非空。
  - 后果:WTG 的爆款/参考**目前到不了 autowriter**。
  - 需手动设置:`UPDATE truth_vault.projects SET mapping_to_autowriter_project_id = '<对应 autowriter 项目 id>' WHERE project_id='WTG_phase1';`(`mapping_to_sanshengliubu_project_id` 同理按需设)。

---

## 5. 本轮新增能力 (Session #13)

- ✅ **tier「参考」**:运营在「流量状态」填「参考」= 够不上爆款但值得参考 → 进飞轮(autowriter 注入权重 +0.15,低于 大爆+0.5/爆+0.3),不计爆款统计。
- ✅ **`v_tier_discrepancy` 视图**:抓"人工标 tier vs 互动量矛盾"供复核(不自动改)。WTG 已抓到 **3 条 under_marked**(标无水花但互动 31–42)。
- ✅ **批量 upsert 提速**(逐行 → 分块,17min → 预期 1–2min)。
- ✅ **`docs/12` daily-sync 排查手册**。

---

## 6. 还差什么 / 待办 (按优先级)

**最上游(决定飞轮能否产生价值):**
- [ ] 🔴 **R-022**:三省六部 vibe_rewriter 真注入 DB 样本(sister-repo,见 `docs/10`)。不解则通道1 空转。
- [ ] 设置 WTG 的 `mapping_to_autowriter_project_id` → 打通通道2。
- [ ] 运营开始在飞书标 **爆贴/参考**(当前 WTG 0 真爆款);并复核 `v_tier_discrepancy` 那 3 条。

**数据扩面:**
- [ ] NUC / NRT 等:填 `sync_config`(feishu_app_token / table_id)→ 接入跑数据。
- [ ] WTG `tier_thresholds` 30/100 [待确认] 由策略 lead 拍板。
- [ ] 验证批量提速:分支 `dry_run=false` 跑一次,确认 `truth_vault.notes`=682 且明显更快。

**运维:**
- [ ] 验证通过后启用 `daily-sync.yml` 的 cron(现注释关闭)。
- [ ] (可选)`docs/12 §6` 的 preflight gate。

---

## 7. 导航

- **速查(本文件)** → 整体进度 / 接线状态 / 待办
- `docs/12` → Daily TV sync 失败排查手册(含两库 secret 坑、报错对照表)
- `docs/10` → sister-repo 跟进项(R-022 等)
- `CURRENT_STATE.md` → 详细历史(Session #9–13)
- PR #20–23 → 本轮全部代码改动(均已并入 main)
