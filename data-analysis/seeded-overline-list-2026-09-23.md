# 铺评过线 · 挡 / 撤 / 放行名单（2026-09-23，D-084 B1 / B2 / A9）

> 生产实查（`truth_vault.notes` + `flywheel_lesson_annotations` + `synced_to_ssll_at`），只列 note_id，不含原文。
> 口径：`comment_maintained_seeded` = 运营已铺的条数（关注 20 / 重点关注⭐️ 50 / 维护评论50条 50），运营 2026-09-22 确认计入评论数。

## 1. BJS / ANSHEN / SPX 三个项目里带 route「铺评工单」的爆/大爆（15 行）

| 项目 | note_id | tier | 评论数 | 已铺 | 扣后 | B1 落地后 | 已策展卡 | ssll 同步标记 |
|---|---|---|---|---|---|---|---|---|
| ANSHEN | ANSHEN_phase1_recvs3O4XJ8meP | 爆 | 51 | 20 | 31 | 挡（铺评工单） | 有 | 无 |
| ANSHEN | ANSHEN_phase1_recvs3O4XJhGXp | 爆 | 51 | 20 | 31 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvsWBVowMCHc | 大爆 | 205 | 20 | 185 | **放行（铺评未跨线 + 起量后干预）** | 有 | 无 |
| BJS | BJS_phase1_recvuxmbVebPZB | 爆 | 73 | 20 | 53 | **放行（铺评未跨线 + 起量后干预）** | 有 | 无 |
| BJS | BJS_phase1_recvtW6XQySdDO | 爆 | 56 | 20 | 36 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvsWBV6nCgEz | 爆 | 53 | 20 | 33 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvtnTv4flVX8 | 爆 | 51 | 20 | 31 | 挡 | 有 | 无 |
| BJS | BJS_phase1_rec27XT4U6QhLu | 爆 | 50 | 20 | 30 | 挡 | 有 | 无 |
| BJS | BJS_phase1_rec27XT4U6Qsnj | 爆 | 50 | 20 | 30 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvuCgfNH1gdb | 爆 | 50 | 20 | 30 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvu8g6PyrAXm | 爆 | 50 | 20 | 30 | 挡 | 有 | 无 |
| BJS | BJS_phase1_rec27XT4U6QmD1 | 爆 | 50 | 20 | 30 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvuBQXSIYw6w | 爆 | 49 | 20 | 29 | 挡 | 有 | 无 |
| BJS | BJS_phase1_recvtidAjYMKC3 | 爆 | 49 | 20 | 29 | 挡 | 有 | 无 |
| SPX | SPX_phase1_recvtWVFOWZVqG | 大爆 | 148 | 50 | 98 | **放行（铺评未跨线 + 起量后干预）** | 无 | 无 |

- **B1 的 12 行**（ops-answers §0.4 那 12 行）= 上表 BJS 里扣后 29–36 的 10 行 + ANSHEN 2 行的同形；全部已在
  2026-09-22 判据点 ⑥ 上线时被记成「铺评工单」，书架（v1.14）/ L2（v1.15）/ 通道 1（D-068）三处都已挡。B1 落地不改变它们。
- **真赢家 3 行**（BJS 205 / 73、SPX 148）现在被误挡；B1 的减法重判落地后下一次夜跑改记「铺评未跨线」，自动回到书架 / L2 / 通道 1。
- **B2「已推 ssll 的 14 行」**：15 行 `synced_to_ssll_at` 全为空。D-068 的自愈回收（每次夜跑跑一遍）已经把它们从 ssll 撤回了，
  最晚在 2026-09-23 的 daily-sync #180（通道 1 步 09:02 UTC）。所以「先问对面再撤」这一步已经来不及：撤回是判据点 ⑥ 上线的
  自动后果，不是这次的动作。对面若已把这些当样本用过，需要他们自己看 `reference_samples` 的变更。
- **书架侧**：v1.14 是实时视图，route 一变当场出架，不需要另外撤。

## 2. A9 · 被闸挡在书架外但已有经验卡的（孤儿卡）

| 项目 | 挡在书架外的 爆/大爆（route 铺评工单） | 其中已策展 |
|---|---|---|
| TUGE | 49 | 31 |
| BJS | 12 | 12 |
| ANSHEN | 2 | 2 |
| SPX | 1 | 0 |

这些卡**不在书架上**（视图实时过滤），不再教写作台；卡本身留在 `flywheel_lesson_annotations` 里当历史，不删。
B1 落地后 BJS 2 张回到书架（SPX 那行没有卡）。TUGE 49 行里 48 行扣后仍不够线（`维护评论50条` 50 条），只 1 行（100−50=50）回来。
