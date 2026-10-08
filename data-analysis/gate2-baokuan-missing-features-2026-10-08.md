# 闸二正例特征补齐 · 237 篇爆款的定向抽取清单（2026-10-08）

**问题**（三仓复核报告 §1.5 / §3 P1）：闸二要算"特征在爆与趴之间有没有区分度"，10-08 实查 411 篇 爆/大爆 里 **237 篇没有特征**（57%）：
on_demand 七个项目 187 篇（它们不进 `features-sync` 的夜跑配额），daily 项目 50 篇（夜跑按 12/晚轮着抽，RIO 排到 2 个月后）。

**做法**：不整项目回填（on_demand 七个项目 2,359 篇、7–9 次 6 小时的 run），只按 `note_ids` 模式定向抽这 237 篇。
`backfill-features.yml` 的 `note_ids` 输入 ≤200 篇一次、`batch` 建议 2（D-077：一篇 53–81 s），所以分两次触发：

| 触发 | 范围 | 篇数 | 预计 | 输入 |
|---|---|---|---|---|
| A | on_demand 七项目的全部爆款 | 187 | 94 批 × ~2.5 min ≈ 4 h（6 h 上限内） | `project=gate2-ondemand` · `batch=2` · `note_ids=`〈清单 A〉 |
| B | daily 项目还没轮到的爆款 | 50 | ~1 h | `project=gate2-daily` · `batch=2` · `note_ids=`〈清单 B〉 |

`run_tag` 留默认 `primary`（这些篇在 primary 下都没答过，不会被跳过）。两次都要避开 `features-sync` 的 12:47 UTC 时段（同一把 worker 锁，撞上会 409 等锁）。
趴的样本已经够（2,064 篇有特征里绝大多数是趴），闸二缺的只是正例这一边。

> 这是 owner 拍板后触发的（LLM 费用：237 篇 × 6 次 Opus 调用）。触发命令：GitHub → Actions → "Backfill features" → Run workflow，把下面清单整段贴进 `note_ids`。

## 清单 A · on_demand 七项目（187 篇）

```
HXZ_FB_recv1yfq8sOEeU,HXZ_FB_recv1ykoKkEIci,HXZ_FB_recv2HR4clUyhX,HXZ_FB_recv2vxBXfrOOr,HXZ_FB_recv1jIHF9eDwY,HXZ_FB_recv1jIHF9i9sl,HXZ_FB_recv1jIHF9lbzZ,HXZ_FB_recv1yfq8sSyhd,HXZ_FB_recv1ykoKkmxTj,HXZ_FB_recv2HR4clsBJJ,HXZ_FB_recv2HR4clyP76,HXZ_FB_recv2kjYAEFMHs,HXZ_FB_recv2uBkY6gXPc,HXZ_FB_recv2vxBXfrYSv,HXZ_QD_recv1j6obpnoLW,HXZ_QD_recv1Ze1eOaSL7,HXZ_QD_recv1Ze1eOqowz,HXZ_QD_recv1L2bW1whuG,NRT_phase2_recuYaP5odK5Dm,NRT_phase2_recuYaP5odwmSD,NRT_phase2_recuYDTRdFGfHg,NRT_phase2_recuYs7CP2R63d,NRT_phase2_recuYWgEJzolkc,NRT_phase2_recuYX9Awv0QR6,NRT_phase2_recuYX9AwvWI23,NRT_phase2_recuYXppKovrbA,NRT_phase2_recuYyYJm2CtBB,NRT_phase2_recuXkwGJK7sa2,NRT_phase2_recuXkwGJKeXlW,NRT_phase2_recuXlgh1jlqf5,NRT_phase2_recuXoBCGwYdFR,NRT_phase2_recuXxBzxxshFP,NRT_phase2_recuXxBzxxT7pL,NRT_phase2_recuYaP5oddKe0,NRT_phase2_recuYaP5odL8WF,NRT_phase2_recuYDTRdF3OvN,NRT_phase2_recuYDTRdF4UCe,NRT_phase2_recuYWgEJzgWlE,NRT_phase2_recuYWgEJzl2sN,NRT_phase2_recuYWgEJzwYuQ,NRT_phase2_recuYX9Awv3dhG,NRT_phase2_recuYX9AwvkVy9,NRT_phase2_recuYXUhTu8tjU,NRT_phase2_recuYyYJm2iiba,NRT_phase2_recuYyYJm2TgVL,NRT_phase2_recuYyYJm2XfKf,NRT_phase2_recuZ8QQXiJmWa,NRT_phase2_recuZkIQtVqTIC,NRT_phase2_recuZkJtsfcojx,NRT_phase2_recuZkyk6BtMRU,NRT_phase3_recv0gJDDrbHy0,NRT_phase3_recv0gJDDrTSJY,NRT_phase3_recv0lniHB0cii,NRT_phase3_recv0mHowIbOMg,NRT_phase3_recv0mHowIttrV,NRT_phase3_recv0naLiZyfIY,NRT_phase3_recv0rz7EHgMId,NRT_phase3_recv0x2oMLdHS9,NRT_phase3_recv12EsNIzHUl,NRT_phase3_recv18huoyyLwL,NRT_phase3_recv2vC9VE3uOD,NRT_phase3_recv4XC684yeAy,NRT_phase3_recv4XC684ZtpC,NRT_phase3_recv0mHowIPiMi,NRT_phase3_recv0mHowIzI97,NRT_phase3_recv0wDwqPT50K,NRT_phase3_recv0x2oML4szO,NRT_phase3_recv11CZ81WWFl,NRT_phase3_recv12EsNIKpkC,NRT_phase3_recv12EsNIWEEK,NRT_phase3_recv12N19vst1i,NRT_phase3_recv12N19vwEfU,NRT_phase3_recv1v9lLXpmCK,NRT_phase3_recv24aqffkYvX,NRT_phase3_recv24aqffqAF1,NRT_phase3_recv2dE1O60uXF,NRT_phase3_recv2P4Pt5ClQ5,NRT_phase3_recv2P4Pt5i75H,NRT_phase3_recv2P4Pt5OvPH,NRT_phase3_recv2TxrnbiTEK,NRT_phase3_recv4TDkN3To7R,NRT_phase3_recv4TzOyjfvPX,NRT_phase3_recv4XC0d7YxWL,NRT_phase3_recv4XC6841gWR,NUC_phase1_recv2jCgov51Yz,NUC_phase1_recv2xd6lzUlFR,NUC_phase1_recv2Z8m1lbHP8,NUC_phase1_recv3rSop58Tu9,NUC_phase1_recv3rSop5CrJk,NUC_phase1_recv46Lai94dYe,NUC_phase1_recv47G0uF8s31,NUC_phase1_recv47G0uFOiGu,NUC_phase1_recv4cv5qkp8wt,NUC_phase1_recv4cv6n9fuIu,NUC_phase1_recv4cv7mLDRzs,NUC_phase1_recv4cv7QqilbZ,NUC_phase1_recv4cv8hq2fOd,NUC_phase1_recv4M1ReJcNvf,NUC_phase1_recv4M1Vya0vH0,NUC_phase1_recv4RnotpFkSa,NUC_phase1_recv4Rnp1TxoRt,NUC_phase1_recv4XiV4BffHj,NUC_phase1_recv4XiV4BlST2,NUC_phase1_recv4XiV4BZY5z,NUC_phase1_recv59erAa5swB,NUC_phase1_recv59erAaml0v,NUC_phase1_recv1HmOGdzLsy,NUC_phase1_recv1nDNccYzgr,NUC_phase1_recv1nGD0hlm7Q,NUC_phase1_recv1nGD0hS6zo,NUC_phase1_recv2lNktp67Uy,NUC_phase1_recv2lNktpLHSb,NUC_phase1_recv2lNktplXJT,NUC_phase1_recv2lNktpmHp0,NUC_phase1_recv2lNktpokW9,NUC_phase1_recv2lNktpRZwk,NUC_phase1_recv2xd6lzdyha,NUC_phase1_recv2xd6lzLAMT,NUC_phase1_recv2xd6lzuQpb,NUC_phase1_recv2YL0GQrYWK,NUC_phase1_recv2YL0GQX1lr,NUC_phase1_recv3EOhVJCooL,NUC_phase1_recv3EOhVJttTR,NUC_phase1_recv3EOhVJx2j0,NUC_phase1_recv3IP6jarMUQ,NUC_phase1_recv3IP6jayWIi,NUC_phase1_recv3K4xf0ICiL,NUC_phase1_recv3rSop5tf1B,NUC_phase1_recv3rSop5wEcv,NUC_phase1_recv3ugA1Qiww4,NUC_phase1_recv46Lb0KvsFi,NUC_phase1_recv47G0uFxzAp,NUC_phase1_recv4bESLyU8Qj,NUC_phase1_recv4cv6IqdxZO,NUC_phase1_recv4LUi9thGJr,NUC_phase1_recv4LYEZqVjyO,NUC_phase1_recv4LYGcBjNmR,NUC_phase1_recv4LYGthVy2I,NUC_phase1_recv4M1Vya1woS,NUC_phase1_recv4M1VyaBKDp,NUC_phase1_recv4M1Vyar7vI,NUC_phase1_recv4M1VyasT9A,NUC_phase1_recv4M1VyasVTK,NUC_phase1_recv4M1Vyax0db,NUC_phase1_recv4RnoI3JA9w,NUC_phase1_recv4RnpAUHfXN,NUC_phase1_recv4RnpTHJU8o,NUC_phase1_recv4XiV4BaEmu,NUC_phase1_recv4XiV4BcyGu,NUC_phase1_recv4XiV4BEgWn,NUC_phase1_recv4XiV4Bk0zL,NUC_phase1_recv4XiV4BNojP,NUC_phase1_recv4XiV4BxxVM,NUC_phase1_recv4XiV4ByOyy,NUC_phase1_recv4ZeTmzsA7x,NUC_phase1_recv4ZeTmzYqRh,NUC_phase1_recv4ZeTmzz1Q5,NUC_phase1_recv59erAaQ4Hh,NUC_phase1_recv59erAaWeiP,TGV_phase1_recuSfObFiQmXs,TGV_phase1_recuSfOe6Q8L7Q,TGV_phase1_recuSfOe6QhbxB,TGV_phase1_recuSfOe6QitoB,TGV_phase1_recuSfOe6QjbFd,TGV_phase1_recuSfOe6QKOSs,TGV_phase1_recuSfOe6QOzI5,TGV_phase1_recuSfOe6Qt0F0,TGV_phase1_recuSfOe6QWXEc,TGV_phase1_recuSfOe6QX0o2,TGV_phase1_recuSfOe6QyHfy,TGV_phase1_recuSVGYqU50hR,TGV_phase1_recuSVGYqUjAcc,TGV_phase1_recuSVGYqUjOG3,TGV_phase1_recuSVGYqUmoN0,TGV_phase1_recuSVGYqUoLl8,TGV_phase1_recuSVGYqUQV0g,TGV_phase1_recuSVGYqUyjuT,TGV_phase1_recuTj1Tp0lW2G,TGV_phase1_recuSfOe6Qp4RN,TGV_phase1_recuSfOe6QpifE,TGV_phase1_recuSVGYqU8bOF,TGV_phase1_recuSVGYqUkRLb,TGV_phase1_recuSVGYqUojOA,TGV_phase1_recuTj1Tp08Fqx,TGV_phase1_recuTj1Tp0eA0K,TGV_phase1_recuTj1Tp0LhpR,TXQ_phase1_recvgXdCLC2mtp
```

分项目：HXZ_FB 14 · HXZ_QD 4 · NRT_phase2 32 · NRT_phase3 34 · NUC_phase1 75 · TGV_phase1 27 · TXQ_phase1 1。

## 清单 B · daily 项目还没轮到的（50 篇）

```
HATHERINE_phase1_recvvVqwhU4bwj,HATHERINE_phase1_recvw1LdlTTJMM,HATHERINE_phase1_recvw6GTUS5LS3,OKMAN_phase1_recvrd83rm2zmO,OKMAN_phase1_recvqtis0iOFsI,OKMAN_phase1_recvqtis0iPI0b,OKMAN_phase1_recvqtis0iVJG0,OKMAN_phase1_recvrd83rma2gZ,OKMAN_phase1_recvrd83rmjBbl,OKMAN_phase1_recvrTMpirB5mF,OKMAN_phase1_recvrTMpirlk43,OKMAN_phase1_recvrTMpirVUg0,OKMAN_phase1_recvsE8E0MPxfg,RIO_phase1_recvf31bFw5VxV,RIO_phase1_recvf31cjh4wEL,RIO_phase1_recvf31cjh7nb4,RIO_phase1_recvgbrQYP7KEh,RIO_phase1_recviUXMzZLlf5,RIO_phase1_recviVcPxKiqqb,RIO_phase1_recviVcPxKPJ8l,RIO_phase1_recvjECRBlSVL1,RIO_phase1_recvjECRBlYT4P,RIO_phase1_recvjW9QAsAzcP,RIO_phase1_recvjWa27qB6BN,RIO_phase1_recvjWa27qDfQE,RIO_phase1_recvjWaHePjpim,RIO_phase1_recvjWaqT27Oj3,RIO_phase1_recvkHLf1pYusP,SPX_phase1_recvsxkitAHF5Q,SPX_phase1_recvsxkitAVzkS,SPX_phase1_recvsxkitAxq5G,SPX_phase1_recvtWVFOWA8T7,SPX_phase1_recvtWVFOWDurZ,SPX_phase1_recvtWVFOWiK3w,SPX_phase1_recvtWVFOWtVc9,SPX_phase1_recvtWVFOWZVqG,SPX_phase1_recvvb62UbfbVY,SPX_phase1_recvsxkitAPscK,SPX_phase1_recvsxkitAULjE,SPX_phase1_recvsxkitAY9DG,SPX_phase1_recvtWVFOW45Gh,SPX_phase1_recvtWVFOWKG3R,SPX_phase1_recvtWVFOWMfb9,SPX_phase1_recvtWVFOWtJ1e,SPX_phase1_recvtWVFOWxcTZ,SPX_phase1_recvuS8Ulpokw5,SPX_phase1_recvvh0Dj2UN5p,SPX_phase1_recvvmoS1rtJrt,XIWU_phase1_recvtcq53BZfiT,XIWU_phase1_recvtLxJaxSNlj
```

分项目：HATHERINE 3 · OKMAN 10 · RIO 15 · SPX 20 · XIWU 2。这 50 篇夜跑迟早会轮到；先抽只是让闸二不用等。

## 清单怎么来的

```sql
with feat as (select distinct subject_id from truth_vault.note_feature_answers
              where subject_type = 'note' and run_tag = 'primary' and extractor like 'llm:%')
select n.project_id, n.tier, string_agg(n.note_id, ',' order by n.note_id)
from truth_vault.notes n left join feat f on f.subject_id = n.note_id
where n.tier in ('爆','大爆') and f.subject_id is null group by 1, 2;
```

跑完后用同一句 SQL 复核应为 0 行；再跑 `scripts/` 里闸二那套。
