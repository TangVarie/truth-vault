# L2 预测层可行性实测（2026-09-16）

## 为什么存在

「数据够不够做 L2」这个问题，之前一直用 roadmap 里的「1k+ 行」当门槛来回答。
那是个错的门槛 —— 行数从来不是瓶颈，**标签口径**和**发布前可得的特征**才是。

这份文档记录一次真实测算：不是「理论上能不能」，是**把打分器跑出来，量出 AUC 和提升倍数**。
所有 SQL 在文末，可直接复跑证伪。

> 结论先说：**能做，但它是「排雷器」不是「选爆器」。**
> 留一项目交叉验证 AUC ≈ 0.61；最差 20% 的爆率是基线的一半；
> 但最高分那 20% 只有 1.4 倍提升，且顶部不单调。

> ⚠️ **2026-09-16 修正**：本文第一版（9/15）的全部数字是在**污染标签**上算的 ——
> 373 个爆款里 79 个（21%）来自刷评、数值推断或运营手标的伪爆贴。
> 清洗后的口径见 [signal-definitions.md](signal-definitions.md)，
> 重算结果和正文实验见文末 **第八节**。旧数字保留在下文，用于对照。

---

## 一、数据底子（够）

| 项 | 数 | 说明 |
|---|---|---|
| notes 总量 | 5,949 | 16 个项目 |
| 有 essence 标注 | 5,714 (96%) | 全部 `prediction_feature` 模式，`posthoc_explanation` 为 0 |
| 标注者 | `claude-opus-4-6` / vocab `v0.2` | 2026-06-04 → 2026-09-16 |
| 正文 ≥50 字 | 5,920 | 标注是从正文来的，没吃到 metrics |

**没有标签泄漏。** 5,714 行全是 `prediction_feature` 模式，标注只看内容不看数据。
这是 D-017 当初把主表定成这个模式换来的 —— 现在直接省掉了一轮重标。

特征词表很紧，正好适合做表格模型（不是自由文本）：

| 特征 | 基数 | 覆盖 |
|---|---|---|
| `emotional_lever` | 12 | 5,714 |
| `human_truth_archetype` | 19 | 5,714 |
| `target_audience` | 9 | 4,822 |
| `content_format` | 8 | 5,249 |
| `intent` | 5 | 2,303（覆盖太低，未用） |
| `direction_subtype` | — | 451（覆盖太低，未用） |

**可训练集**：标签 ∈ {爆, 大爆, 趴} 且有特征 = **4,672 行 / 364 正例（7.8%）**。
四个特征全齐的 = 3,932 行 / 285 正例。

---

## 二、信号是真的（且扛得住分层）

`emotional_lever` 的全局爆率分布（n≥30）：

| lever | n | 爆率 | lift |
|---|---|---|---|
| 罪恶感撬动 | 274 | 12.0% | 1.55 |
| 羞耻撬动 | 312 | 11.9% | 1.52 |
| 恐惧撬动 | 392 | 11.2% | 1.44 |
| 焦虑撬动 | 1,024 | 11.0% | 1.42 |
| 愤怒撬动 | 98 | 9.2% | 1.18 |
| 好奇驱动 | 229 | 9.2% | 1.18 |
| 虚荣撬动 | 57 | 7.0% | 0.90 |
| 归属感建立 | 42 | 4.8% | 0.61 |
| 共鸣释放 | 1,461 | 4.5% | 0.58 |
| 信息差利用 | 683 | 4.0% | 0.51 |
| 认同感建立 | 78 | 2.6% | 0.33 |

前五名全是**负面情绪撬动**，后四名全是**正面共鸣/认同**。3–4.6 倍差距，单调，方向可解释。

关键问题：这会不会只是「项目混合」的假象？做项目内分层，**不是**：

| 项目 | 负面撬动 | 其他 | 倍数 |
|---|---|---|---|
| NUC_phase1 | **19.9%** (n=376) | 5.0% (n=201) | **4.0×** |
| NRT_phase2 | **19.0%** (n=184) | 3.3% (n=209) | **5.8×** |
| SPX_phase1 | 10.8% (n=102) | 5.6% (n=213) | 1.9× |
| OKMAN_phase1 | 16.9% (n=71) | 11.7% (n=214) | 1.4× |
| NRT_phase3 | 8.5% (n=413) | 6.4% (n=140) | 1.3× |
| HXZ_FB | 10.7% (n=112) | 8.6% (n=35) | 1.2× |
| TXQ_phase1 | 9.4% (n=32) | 8.1% (n=74) | 1.2× |
| RIO_phase1 | 6.7% (n=15) | 6.2% (n=501) | 1.1× |
| XIWU_phase1 | 4.0% (n=126) | 4.9% (n=61) | **0.8×**（反向） |

两个最大、最干净的项目（NUC、NRT_2）都是 4–6 倍。只有 XIWU 反向。

`human_truth_archetype` 同样有梯度（n≥40）：
归属缺失 17.8% / 代际冲突 11.8% / 情感缺位 11.5% / 同辈比较 11.2% ⟷
消费愉悦 3.6% / 时间流逝感 2.6% / 自由意志 2.1%。跨度 8 倍。

---

## 三、实测：留一项目交叉验证

因为**时间和项目几乎完全共线**（见第四节），唯一诚实的留出方式是按项目留出：
拿其余 15 个项目算每个特征值的对数几率，去给留出项目打分，**在项目内排序**。

打分器 = 四类特征对数几率的平均（Laplace 平滑）。故意做得很笨，只为量信号上限。

| 留出项目 | n | 正例 | AUC |
|---|---|---|---|
| NRT_phase2 | 393 | 42 | **0.762** |
| NUC_phase1 | 577 | 85 | 0.633 |
| HXZ_QD | 146 | 6 | 0.629 |
| SPX_phase1 | 315 | 23 | 0.625 |
| TXQ_phase1 | 106 | 9 | 0.614 |
| OKMAN_phase1 | 285 | 37 | 0.593 |
| HXZ_FB | 147 | 15 | 0.593 |
| RIO_phase1 | 516 | 32 | 0.570 |
| NRT_phase3 | 553 | 44 | 0.556 |
| TUGE_phase1 | 53 | 39 | 0.544 |
| XIWU_phase1 | 187 | 8 | 0.506 |

**按正例加权 AUC = 0.61。**

项目内按分数分五档（剔除 TGV/TUGE，见第四节）：

| 档位 | n | 爆款 | 爆率 |
|---|---|---|---|
| 第 1 档（分最高 20%） | 927 | 88 | 9.49% |
| 第 2 档 | 924 | 95 | **10.28%** |
| 第 3 档 | 920 | 56 | 6.09% |
| 第 4 档 | 917 | 41 | 4.47% |
| 第 5 档（分最低 20%） | 917 | 31 | **3.38%** |
| 基线 | 4,605 | 311 | 6.75% |

- 上 40% vs 下 40% = 9.89% vs 3.93% = **2.5 倍**
- **第 2 档 > 第 1 档 —— 顶部不单调。** 这个模型找得准「差」，找不准「最好」。
- 砍掉最低那 20%：少发 **19.9%** 的量，只丢 **10.0%** 的爆款。

---

## 四、三个证伪掉的做法（负面结果，别再试）

### ① 单项目模型（用项目自己的历史训练）—— 更差

按项目内发布时间切 70/30，用自己的前 70% 训练：

| 项目 | 测试 n | 正例 | AUC |
|---|---|---|---|
| NRT_phase2 | 117 | 6 | 0.829 |
| NRT_phase3 | 165 | 13 | 0.710 |
| NUC_phase1 | 171 | 44 | 0.603 |
| RIO_phase1 | 153 | 18 | 0.536 |
| OKMAN_phase1 | 84 | 11 | 0.507 |
| TXQ_phase1 | 30 | 8 | 0.489 |
| SPX_phase1 | 93 | 13 | 0.439 |
| HXZ_FB | 42 | 6 | 0.421 |
| TUGE_phase1 | 15 | 13 | 0.346 |
| HXZ_QD | 42 | 5 | **0.270** |

**加权 AUC = 0.54，一半项目低于 0.5（不如抛硬币）。**
原因：单项目正例太少（HXZ_QD 一共 6 个），学的是噪声。
**跨项目合池 + 项目内排序才是对的架构。**

### ② 换成数值标签（项目内互动量前 20%）—— 更差

正例从 373 涨到 993（2.7 倍），AUC **反而从 0.61 掉到 0.56**。
BJS 0.445 / HXZ_FB 0.445 / HXZ_QD 0.446 / TXQ 0.410 全部低于随机。

**运营手标的「爆」比纯数值标签更可预测。** 因为运营在判「这条是不是真起量」，
会把刷量、小基数、数据异常剔掉；纯取前 20% 在互动量中位数=1 的项目里就是纯噪声。

→ **不要换标签。现在的 `tier` 就是对的。**

### ③ 按时间做留出验证 —— 做不了

每个项目的笔记基本都落在同一个季度：

| 季度 | 主要项目 |
|---|---|
| 2025Q4 | NUC(577) NRT_3(553) NRT_2(325) HXZ_FB(147) HXZ_QD(146) |
| 2026Q1 | RIO(319) WTG(294) |
| 2026Q2 | WTG(393) RIO(195) TXQ(106) |
| 2026Q3 | LNKT(340) SPX(315) OKMAN(237) XIWU(187) BJS(178) ANSHEN(175) TUGE(53) |

**时间 ≈ 项目，完全共线。** 所以下面这张表看着像「效果在衰减」：

| 季度 | 负面撬动爆率 | 其他爆率 | 倍数 |
|---|---|---|---|
| 2025Q3 | 50.0% (n=36) | 15.6% (n=45) | 3.2× |
| 2025Q4 | 13.2% (n=1177) | 4.6% (n=571) | 2.9× |
| 2026Q1 | 0.0% (n=29) | 2.1% (n=584) | — |
| 2026Q2 | 7.5% (n=106) | 5.2% (n=636) | 1.4× |
| 2026Q3 | 7.3% (n=751) | 6.8% (n=736) | **1.07×** |

**但这张表不能用来下结论** —— 「规律失效了」和「换了一批客户」在现有数据里**不可区分**。
要拆开，只有一个办法：**同一个项目跨季度持续投**。目前没有任何项目满足。

---

## 五、已知的硬伤

### ① 标签口径不统一（最严重）

各项目「爆」的互动量中位数：

| 项目 | 爆的中位互动 | 趴的中位互动 |
|---|---|---|
| TGV_phase1 | 925 | — |
| NRT_phase2 | 589 | 3 |
| NRT_phase3 | 526 | 4 |
| RIO_phase1 | 466 | 2 |
| OKMAN_phase1 | 449 | 4 |
| NUC_phase1 | 294 | 4 |
| XIWU_phase1 | 197 | 4 |
| HXZ_FB | 182 | 6 |
| SPX_phase1 | 80 | 2 |
| TUGE_phase1 | 52 | 3 |
| WTG_phase1 | 36 | 1 |
| BJS_phase1 | 13 | 0 |
| **ANSHEN_phase1** | **1** | 1 |

**ANSHEN 的「爆」（中位互动 1）比 NUC 的「趴」（中位互动 4）还差。**
→ 分数**永远不能跨项目比**，只能项目内排序。上面所有测算都遵守了这条。

### ② 两个项目是爆款集锦，不是全量日志

TGV_phase1 爆率 **100%**（14/14），TUGE_phase1 **73.6%**（39/53）。
这两张表记的是精选案例，不是投放全量。留在训练集里会毒化基线。
→ 打分时必须排除（第三节的分档表已排除）。

### ③ 正例太少，撑不起文本模型

364 个正例、7.8% 不平衡。够喂 4 个低基数标签，**不够训练读正文的模型**。

### ④ 正文完全没用上

5,920 行有 ≥50 字正文，目前一个字都没进模型。
**这是唯一能把 0.61 推到 0.7+ 的路**，也是唯一还没试过的路。

---

## 六、复现 SQL

以下四段可直接在 Supabase（project `kduysqedrclrfevrxiie`）执行。

### 打分器 + 留一项目 AUC

```sql
WITH d AS (
  SELECT note_id, project_id, CASE WHEN tier IN ('爆','大爆') THEN 1 ELSE 0 END y,
         emotional_lever, content_format, human_truth_archetype, target_audience
  FROM truth_vault.notes WHERE emotional_lever IS NOT NULL AND tier IN ('爆','大爆','趴')
), f AS (
  SELECT note_id,'L:'||emotional_lever feat FROM d
  UNION ALL SELECT note_id,'F:'||content_format FROM d WHERE content_format IS NOT NULL
  UNION ALL SELECT note_id,'A:'||a FROM d, unnest(human_truth_archetype) a
  UNION ALL SELECT note_id,'U:'||a FROM d, unnest(target_audience) a
), projs AS (SELECT DISTINCT project_id FROM d), lo AS (
  SELECT p.project_id test_p, f.feat,
         ln((count(*) FILTER (WHERE d.y=1)+1.0)/(count(*) FILTER (WHERE d.y=0)+1.0)) w
  FROM projs p JOIN d ON d.project_id <> p.project_id JOIN f ON f.note_id=d.note_id
  GROUP BY 1,2
), scored AS (
  SELECT d.note_id, d.project_id, d.y, avg(lo.w) score
  FROM d JOIN f ON f.note_id=d.note_id JOIN lo ON lo.test_p=d.project_id AND lo.feat=f.feat
  GROUP BY 1,2,3
), r AS (
  SELECT project_id, y, rank() OVER (PARTITION BY project_id ORDER BY score) rk FROM scored
)
SELECT project_id, count(*) n, count(*) FILTER (WHERE y=1) pos,
  round(((sum(rk) FILTER (WHERE y=1) - count(*) FILTER (WHERE y=1)*(count(*) FILTER (WHERE y=1)+1)/2.0)
        / NULLIF(count(*) FILTER (WHERE y=1)::numeric * count(*) FILTER (WHERE y=0),0))::numeric, 3) auc
FROM r GROUP BY 1 HAVING count(*) FILTER (WHERE y=1) >= 5 ORDER BY pos DESC;
```

把末段换成 `ntile(5) OVER (PARTITION BY project_id ORDER BY score DESC)` 分组，
并加 `WHERE project_id NOT IN ('TGV_phase1','TUGE_phase1')`，即得第三节分档表。

### 负面撬动的项目内分层

```sql
WITH lab AS (
  SELECT project_id,
         CASE WHEN emotional_lever IN ('罪恶感撬动','羞耻撬动','恐惧撬动','焦虑撬动','愤怒撬动')
              THEN '负面撬动' ELSE '其他' END AS grp,
         CASE WHEN tier IN ('爆','大爆') THEN 1 WHEN tier='趴' THEN 0 END AS y
  FROM truth_vault.notes WHERE emotional_lever IS NOT NULL
)
SELECT project_id,
  count(*) FILTER (WHERE grp='负面撬动') n_neg, round(100.0*avg(y::numeric) FILTER (WHERE grp='负面撬动'),1) neg_pct,
  count(*) FILTER (WHERE grp='其他')     n_oth, round(100.0*avg(y::numeric) FILTER (WHERE grp='其他'),1)     oth_pct
FROM lab WHERE y IS NOT NULL GROUP BY 1
HAVING count(*) FILTER (WHERE y=1) >= 8 ORDER BY count(*) FILTER (WHERE y=1) DESC;
```

### 标签口径核对

```sql
SELECT project_id,
  percentile_disc(0.5) WITHIN GROUP (ORDER BY interactions)
    FILTER (WHERE tier IN ('爆','大爆') AND interactions IS NOT NULL) med_int_bao,
  percentile_disc(0.5) WITHIN GROUP (ORDER BY interactions)
    FILTER (WHERE tier='趴' AND interactions IS NOT NULL) med_int_pa
FROM truth_vault.notes GROUP BY 1
HAVING count(*) FILTER (WHERE tier IN ('爆','大爆')) > 0
ORDER BY med_int_bao DESC NULLS LAST;
```

### 时间/项目共线性核对

```sql
SELECT date_trunc('quarter', publish_time)::date q, project_id, count(*) n
FROM truth_vault.notes
WHERE emotional_lever IS NOT NULL AND publish_time IS NOT NULL AND tier IN ('爆','大爆','趴')
GROUP BY 1,2 HAVING count(*) >= 40 ORDER BY 1, 3 DESC;
```

---

## 七、结论

| 问题 | 答案 |
|---|---|
| 能不能做 L2？ | **能。** 无泄漏、词表紧、4,672 行可训练、信号扛得住项目内分层 |
| 做成什么样？ | **跨项目合池训练 + 项目内排序。** 单项目模型实测更差（0.54） |
| 用什么标签？ | **就用现在的 `tier`。** 换数值标签实测更差（0.56） |
| 效果多大？ | AUC 0.61；砍掉最低 20%，少发 19.9% 的量只丢 10% 的爆款 |
| 不能指望什么？ | **不能预测哪条会爆。** 顶档只有 1.4 倍，且第 2 档反超第 1 档 |
| 最大风险？ | 标签口径不统一（ANSHEN 的爆 < NUC 的趴）；跨项目比分数必错 |
| 天花板在哪？ | 5,920 行正文一个字没用上。这是 0.61 → 0.7+ 唯一的路 |

**最实际的一条**：第二节那张表（负面撬动 3–6 倍）本身就是可交付物，
**不需要任何模型**。先把它变成运营的默认动作，收益大于先去搭预测服务。


---

## 八、2026-09-16 续：清洗标签 + 正文进模型

### 8.1 先清洗标签

9/15 的 0.61 是在污染标签上算的。按 [signal-definitions.md](signal-definitions.md)
第八节的口径清洗（排除 数值推断 / 伪爆贴 / 刷 50 评 / 互动低于本项目趴中位），
正例 **373 → 294**，重跑留一项目交叉验证：

| 留出项目 | 正例 | AUC（污染） | AUC（清洗） | 变化 |
|---|---|---|---|---|
| NRT_phase2 | 42 | 0.762 | 0.769 | +0.007 |
| TUGE_phase1 | 39→11 | 0.544 | **0.662** | **+0.118** |
| HXZ_FB | 15→14 | 0.593 | 0.607 | +0.014 |
| OKMAN_phase1 | 37 | 0.593 | 0.604 | +0.011 |
| NRT_phase3 | 44→43 | 0.556 | 0.574 | +0.018 |
| SPX_phase1 | 23 | 0.625 | 0.625 | 0 |
| XIWU_phase1 | 8→7 | 0.506 | 0.524 | +0.018 |
| NUC_phase1 | 85 | 0.633 | 0.616 | −0.017 |
| **RIO_phase1** | **32→13** | 0.570 | **0.464** | **−0.106** |
| **加权** | **340→275** | **0.612** | **0.624** | **+0.012** |

**整体只涨 0.012，但分项目变化很大。** 两个极端值得看：

- **TUGE 0.544 → 0.662**：清掉 26 条刷评爆贴之后才露出真实水平。
- **RIO 0.570 → 0.464**：丢了 19/32 个正例（10 伪爆 + 3 数值推断 + …）。
  **之前那 0.57 有一部分是模型学会了认「伪爆贴」这个类别** —— 那 10 条大概有共同特征。
  假信号一拿掉，RIO 露出低于随机的真实水平。

> **清洗的价值不在 AUC 涨多少，在于现在这个数字是真的。**
> 之前每 5 个正例里有 1 个是假的。

### 8.2 正文进模型

`title` / `body` / `hashtags` 三列**全空**（13 / 0 / 0 行），正文全在 `raw_content`
（4,804 行有标签且 ≥50 字，中位 260 字）。

做法：字符二元组（df ≥ 40 且 ≤ 30% 语料），同一套对数几率打分器、同一套留一项目验证。
**同一批行**做三方对比，口径完全可比：

| 留出项目 | 正例 | 只用标签 | 只用正文 | 标签+正文 |
|---|---|---|---|---|
| NRT_phase2 | 42 | 0.765 | 0.758 | **0.769** |
| NUC_phase1 | 85 | **0.618** | 0.599 | 0.611 |
| NRT_phase3 | 41 | 0.596 | 0.696 | **0.695** |
| OKMAN_phase1 | 34 | **0.609** | 0.557 | 0.582 |
| HXZ_FB | 14 | 0.607 | 0.619 | **0.638** |
| RIO_phase1 | 13 | 0.461 | 0.626 | **0.652** |
| TUGE_phase1 | 11 | **0.662** | 0.571 | 0.584 |
| XIWU_phase1 | 7 | **0.527** | 0.415 | 0.446 |
| **SPX_phase1** | 23 | **0.623** | **0.320** | **0.232** |
| **加权（全部）** | **270** | **0.628** | 0.606 | 0.610 |
| **加权（去 SPX）** | **247** | 0.629 | 0.633 | **0.646** |

**读法：**

1. **正文单独用 ≈ 标签单独用**（0.606 vs 0.628），但**两者强弱的项目分布完全不同** ——
   NRT_3 标签 0.596 / 正文 0.696，RIO 标签 0.461 / 正文 0.626。互补。
2. **合并在大多数项目确实加分**：去掉 SPX 后 0.646 > 0.629，是三者里最高的。
3. **SPX 一个项目把全局拖垮**（合并 0.232，比随机反向得多）。

### 8.3 SPX 为什么反向

排除掉的假设：**不是同文案铺多账号**。SPX 文案重复率只有 3.9%，
而重复率最高的 RIO（27.8%）正文模型反而是好的（0.626）。

真实原因是**正文长度**：

| SPX | 条数 | 正文中位长度 | 互动中位 |
|---|---|---|---|
| 爆 | 29 | **118 字** | 80 |
| 趴 | 386 | **253 字** | 2 |

SPX 的爆贴正文只有趴贴的一半长。其它项目没这个规律，
跨项目学来的字符权重在 SPX 上系统性反向 —— 模型把「长文案」当成爆的信号，
在 SPX 正好反过来。

→ **这不是 bug，是真实的项目差异。** 也再次印证第五节 ① 的结论：
**跨项目合池训练可以，但必须项目内排序，且要接受个别项目会反向。**

### 8.4 所以正文该不该上

**该上，但不是现在这个上法。**

- 字符二元组的天花板就在这里了（0.646 去 SPX）。它学的是字面，学不到「这是个提问帖」
  「这是在制造对立」这种结构。
- 真正能往上推的是**让 LLM 从正文里抽发布前可得的结构化特征**
  （钩子类型 / 开篇形式 / 身份代入 / 具体性 / 冲突强度），再进同一套验证。
  那是下一步，不是这一步。
- 而且在做那件事之前，**投流信号的缺失比正文特征更卡脖子** ——
  见 [signal-definitions.md](signal-definitions.md) 第三节。
  没有「这条有没有获得曝光机会」，再好的内容特征也解释不了「好内容为什么没爆」。

### 8.5 三方对比的复现 SQL

见 git 历史里本次提交的 commit message，或直接改第六节那段打分器：
把 `f` 这个 CTE 换成字符二元组 + 标签的并集，加一个 `kind` 列做三方切分。
关键参数：`left(raw_content, 600)`、`regexp_replace(..., '[^\u4e00-\u9fa5a-zA-Z0-9]', '', 'g')`、
二元组 `df >= 40 AND df <= 语料量*0.30`。
