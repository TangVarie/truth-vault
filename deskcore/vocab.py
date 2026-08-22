"""deskcore/vocab.py — 发牌用的受控词表闭集。

权威源是 `docs/05-controlled-vocab.md`(v0.2)。改这里必须同步改那边, 并按
docs/05 开头的规矩建一条 DECISIONS 记录。

为什么要有这个文件
------------------
TV 的受控词表有 11 个维度, 但其中 5 个 essence 维度【只以自然语言存在】于
`prompts/essence_annotator.md` 的 prompt 正文和 docs/05 的表格里, 没有任何
代码化闭集 —— `onboarder/vocab.py` 只硬编码了 7 组(content_format /
target_audience / tier / tier_source / intent / schema_family / category)。

发牌(draw_angles)必须在闭集上做无放回抽样, 所以这里把缺的 5 组补上:
emotional_lever(12) / human_truth_archetype(19) / trend_dependencies(10) /
emotional_valence(3) / emotional_intensity(3)。

surface 侧的句式与切入角度不来自 docs/05, 而是从 autowriter 搬过来的
(generator.py 的 TITLE_STRUCTURE_MATRIX / WORD_TILTS / CREATIVE_ROLES_POOL)。
这符合 README 原则 2 的分层: essence 维度穿越周期、surface 维度会过气,
两边各自演进, 不混在一个字段里。
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════
# Essence 层 —— 权威源 docs/05-controlled-vocab.md
# ══════════════════════════════════════════════════════════════════════

# docs/05 §3 (12 值). 负向 5 + 正向 5 + 中性 2。
EMOTIONAL_LEVERS: tuple[str, ...] = (
    "焦虑撬动", "羞耻撬动", "恐惧撬动", "愤怒撬动", "罪恶感撬动",
    "造梦投射", "认同感建立", "归属感建立", "共鸣释放", "虚荣撬动",
    "好奇驱动", "信息差利用",
)

# docs/05 §4 —— valence 由 lever【唯一决定】, 不是独立维度, 不参与抽样。
# 抽到 lever 之后派生出来, 只用于给模型讲清楚这一篇的情绪方向。
LEVER_TO_VALENCE: dict[str, str] = {
    "焦虑撬动": "negative", "羞耻撬动": "negative", "恐惧撬动": "negative",
    "愤怒撬动": "negative", "罪恶感撬动": "negative",
    "造梦投射": "positive", "认同感建立": "positive", "归属感建立": "positive",
    "共鸣释放": "positive", "虚荣撬动": "positive",
    "好奇驱动": "neutral", "信息差利用": "neutral",
}

EMOTIONAL_VALENCES: tuple[str, ...] = ("positive", "negative", "neutral")

# docs/05 §5 (3 值)。参与抽样 —— 同一个 lever 配不同强度, 出来的稿子差别很大。
EMOTIONAL_INTENSITIES: tuple[str, ...] = ("low", "medium", "high")

# docs/05 §6 (19 值). 关系 5 / 自我 4 / 焦虑 4 / 缺失 3 / 欲望 3。
HUMAN_TRUTH_ARCHETYPES: tuple[str, ...] = (
    "同辈比较", "伴侣关系", "代际冲突", "职场关系", "宠物相关",
    "自我形象维护", "身份认同", "时间流逝感", "自由意志",
    "阶层焦虑", "经济焦虑", "健康焦虑", "育儿焦虑",
    "情感缺位", "归属缺失", "认同缺失",
    "控制感渴望", "自我提升", "消费愉悦",
)

# docs/05 §7 (10 值). 多选, 且「通用」排他。
TREND_DEPENDENCIES: tuple[str, ...] = (
    "特定平台事件", "特定IP引用", "时事热点", "季节性事件", "节日",
    "行业事件", "当代流行词", "时代语言范式", "平台话术", "通用",
)

# docs/05 §7 —— 「通用」是排他值: 含通用则不含其他。
TREND_EXCLUSIVE: str = "通用"

# docs/05 §7 的三级时间分层, 供"想要穿越周期 vs 想要当下感"的加权抽样。
TREND_HALFLIFE_TIER: dict[str, str] = {
    "通用": "perpetual",           # 5 年+
    "时代语言范式": "era_idiom",     # 2-3 年
    "平台话术": "era_idiom",
    "特定IP引用": "short",
    "行业事件": "short",
    "当代流行词": "short",          # 6-12 月
    "特定平台事件": "short",
    "时事热点": "short",
    "季节性事件": "short",
    "节日": "short",
}

# docs/05 §2 (8 值) —— 与 onboarder/vocab.py:CONTENT_FORMATS 一致。
CONTENT_FORMATS: tuple[str, ...] = (
    "情感叙事", "认知重构", "横评对比", "教程攻略",
    "直给推荐", "场景植入", "提问求助", "反差破圈",
)

# docs/05 §8 (11 值) —— 与 onboarder/vocab.py:TARGET_AUDIENCES 一致。
TARGET_AUDIENCES: tuple[str, ...] = (
    "年轻女性", "中年女性", "银发女性", "年轻男性", "中年男性", "银发男性",
    "学生党", "宝妈", "伴侣家人", "病患家属", "通用",
)

# docs/05 §1 (5 值)。
INTENTS: tuple[str, ...] = ("traffic", "conversion", "educational", "mixed", "other")


# ══════════════════════════════════════════════════════════════════════
# 边界规则 —— docs/05 §3 的三组易混判据
#
# 抽到相应 lever 时, 把对应那条判据一起给模型。docs/05 花了 40 行讲这三组
# 怎么分, 光给一个标签名模型多半会混。
# ══════════════════════════════════════════════════════════════════════

LEVER_BOUNDARY_RULES: dict[str, str] = {
    "焦虑撬动": (
        "焦虑 = 偏「担心」: 对未来不确定性, 模糊、长程、未发生。"
        "如果你写的是具体已发生的威胁(具体诊断/具体某人说的话), 那是恐惧不是焦虑。"
        "标志词: 万一、以后、再不…就"
    ),
    "恐惧撬动": (
        "恐惧 = 偏「怕」: 对具体威胁的反应, 具体、即时、有对象。"
        "必须有一个具体已发生的事件或可指的对象(医生的诊断、某人当面说的话)。"
        "写成模糊的未来担心就变成焦虑了。标志词: 刚才、医生说、她当面说"
    ),
    "虚荣撬动": (
        "虚荣 = 让读者【现在就感到】自己优于某个对照群体(superiority, 现在时)。"
        "如果你写的是「成为你想成为的样子」那是造梦投射不是虚荣。"
    ),
    "造梦投射": (
        "造梦 = 给读者描绘【他想成为的样子】(aspiration, 未来时)。"
        "如果你写的是「懂的人才知道, 别买错」那是虚荣撬动不是造梦。"
    ),
    "罪恶感撬动": (
        "罪恶感 = 感到【现在做得不够】(对不起谁)。"
        "如果你写的是「将来会后悔」那是焦虑撬动不是罪恶感。"
    ),
}


# ══════════════════════════════════════════════════════════════════════
# Surface 层 —— 从 autowriter/generator.py 搬来
#
# 这些不在 docs/05 里, 因为它们是表层(半衰期 6-12 个月), 本来就该独立演进。
# 项目自己配了 custom_roles 时优先用项目的 —— 当年 slot coordinates 被移除
# (generator.py:1576-1584)的原因就是通用角度池跟项目自己的 role 设定打架,
# 按项目 opt-in 就不打架了。
# ══════════════════════════════════════════════════════════════════════

# autowriter/generator.py:1259
TITLE_STRUCTURES: tuple[str, ...] = (
    "疑问句", "数字清单", "对比反转", "场景直述",
    "第一人称自白", "比喻起手", "感叹共鸣", "对白引语",
)

# autowriter/generator.py:1270
WORD_TILTS: tuple[str, ...] = (
    "克制", "口语", "反差", "感性", "理性", "文艺", "冷静", "自嘲",
)

# autowriter/generator.py:1985 CREATIVE_ROLES_POOL 的 (id, name, 指令) 三元组。
DEFAULT_ANGLES: tuple[dict[str, str], ...] = (
    {"id": "narrative", "name": "叙事角",
     "brief": "以一个具体的生活场景或真实故事切入, 产品自然融入叙事, 不要开篇讲卖点。"
              "让读者先被情境带入, 再自然意识到这是什么。"},
    {"id": "insight", "name": "洞察角",
     "brief": "从一个反直觉、出乎意料或被大多数人忽视的角度切入, 制造认知惊喜或反转。"
              "让读者产生「哦原来是这样」。避免常规切入方式。"},
    {"id": "empathy", "name": "共情角",
     "brief": "从目标用户当下最真实的情绪或生活状态出发, 情绪共鸣先于产品信息。"
              "让读者觉得「这说的就是我」, 然后才自然引出产品。"},
    {"id": "contrast", "name": "对比角",
     "brief": "以「之前 vs 之后」「以为 vs 实际」等对比结构切入, 让差异成为核心张力。"
              "对比要具体可感, 不要抽象泛泛。"},
    {"id": "tips", "name": "干货角",
     "brief": "以实用信息、技巧或方法论为主轴, 产品作为解决方案自然嵌入。"
              "读者应该能带走具体可操作的内容, 而不只是情绪感受。"},
    {"id": "occasion", "name": "场合角",
     "brief": "锁定一个具体的使用时刻或生活节点(下班后、周末早晨、聚会前夜), "
              "让产品成为那个时刻的专属搭档。场合越具体, 代入感越强。"},
)

# prompts/flywheel_curator.md:31 给的 hook_type 枚举。策展卡那边是自由文本短语
# (curate_flywheel_lessons.py:98-107 明说不查闭集), 这里收敛成闭集只为发牌用。
HOOK_TYPES: tuple[str, ...] = (
    "痛点共鸣", "反差", "福利", "悬念", "身份认同", "场景代入", "信息差",
)


# ══════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════

def valence_of(lever: str) -> str:
    """由 lever 派生情绪极性(docs/05 §4: valence 由 lever 唯一决定)。"""
    return LEVER_TO_VALENCE.get(lever, "neutral")


def normalize_trends(trends: list[str]) -> list[str]:
    """应用 docs/05 §7 的排他规则: 含「通用」则只保留「通用」。"""
    cleaned = [t for t in trends if t in TREND_DEPENDENCIES]
    if TREND_EXCLUSIVE in cleaned:
        return [TREND_EXCLUSIVE]
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for t in cleaned:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def boundary_rules_for(lever: str) -> str:
    """抽到某 lever 时要一并给模型的判别指令; 没有就返回空串。"""
    return LEVER_BOUNDARY_RULES.get(lever, "")


def combination_space() -> int:
    """理论组合空间大小, 用于 draw_angles 判断 n 是否离撞车还很远。

    只算参与无放回抽样的四个主维度; trend/intensity/tilt 是叠加项, 不计入。
    """
    return (
        len(EMOTIONAL_LEVERS)
        * len(HUMAN_TRUTH_ARCHETYPES)
        * len(CONTENT_FORMATS)
        * len(TITLE_STRUCTURES)
    )


def vocab_reference() -> str:
    """人类可读闭集清单, 给 MCP 工具描述 / system prompt 用。

    输出模式沿用 onboarder/vocab.py:vocab_reference()。
    """
    return (
        f"emotional_lever({len(EMOTIONAL_LEVERS)}): " + " / ".join(EMOTIONAL_LEVERS) + "\n"
        f"human_truth_archetype({len(HUMAN_TRUTH_ARCHETYPES)}): " + " / ".join(HUMAN_TRUTH_ARCHETYPES) + "\n"
        f"content_format({len(CONTENT_FORMATS)}): " + " / ".join(CONTENT_FORMATS) + "\n"
        f"target_audience({len(TARGET_AUDIENCES)}): " + " / ".join(TARGET_AUDIENCES) + "\n"
        f"trend_dependencies({len(TREND_DEPENDENCIES)}, 多选, 「通用」排他): " + " / ".join(TREND_DEPENDENCIES) + "\n"
        f"emotional_intensity({len(EMOTIONAL_INTENSITIES)}): " + " / ".join(EMOTIONAL_INTENSITIES) + "\n"
        f"title_structure({len(TITLE_STRUCTURES)}): " + " / ".join(TITLE_STRUCTURES) + "\n"
        f"hook_type({len(HOOK_TYPES)}): " + " / ".join(HOOK_TYPES) + "\n"
        f"intent({len(INTENTS)}): " + " / ".join(INTENTS) + "\n"
        f"(emotional_valence 由 emotional_lever 唯一决定, 不独立标)"
    )
