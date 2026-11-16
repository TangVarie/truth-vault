"""scripts/model_prices.py — 模型花费只在这一个文件里算 (D-157, 2026-11-16)。

三样东西, 各带来源和日期:
  · PRICES                  官方标价, 美元 / 百万 token (输入, 输出)。原先在 mask_external_names.py, 11-16 搬到这里,
                            那边改成从这里 import, 数字一个没变。
  · RELAY_PRICE_MULTIPLIER  中转站在标价上乘的倍数。**假设值**: 抄自 autowriter/config.py (那边自己写着没对过现在
                            这家中转站的账单), truth-vault 从没配过、也没对过账。
  · CNY_PER_USD             美元折人民币。**假设值**: 哪个仓都没配过, 和 linkcheck 的默认汇率取同一个数。

两个假设值没对过账单之前, 这里算出来的「元」一律带「按假设价估算」的标记 (ASSUMED = True); 中转站回报的 token 数
才是实数。花费的硬上限因此按 token 算 (first_image_trial.py), 不按元。
只用标准库, 不 import 别的脚本。
"""
from __future__ import annotations

# 官方标价 (美元 / 百万 token: 输入, 输出)。只用来估算; 中转站实价可能不同。
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}

RELAY_PRICE_MULTIPLIER = 1.8      # 假设 · 2026-11-16 · 来源 autowriter/config.py RELAY_PRICE_MULTIPLIER (未对账)
CNY_PER_USD = 7.2                 # 假设 · 2026-11-16 · 哪个仓都没配过 (linkcheck 默认汇率同数)
ASSUMED = True                    # 上面两个数对过一次中转站账单之后才改成 False
ASSUMED_NOTE = "按假设价估算 (中转站倍数 1.8、汇率 7.2 都没对过账单)"

# 输出 token 的标价是输入的几倍 (两档模型都是 5 倍)。token 硬上限把输出按这个倍数折成「输入当量」。
OUTPUT_WEIGHT = 5


def usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """按官方标价的美元数; 不认识的模型回 None (不猜)。"""
    price = PRICES.get(model)
    if not price:
        return None
    return input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]


def yuan(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """按假设的倍数和汇率折成人民币; 不认识的模型回 None。调用方打印时要带 ASSUMED_NOTE。"""
    base = usd(model, input_tokens, output_tokens)
    return None if base is None else base * RELAY_PRICE_MULTIPLIER * CNY_PER_USD


def weighted_tokens(input_tokens: int, output_tokens: int) -> int:
    """输入当量 token = 输入 + 5 × 输出。花费硬上限数的是这个。"""
    return int(input_tokens) + OUTPUT_WEIGHT * int(output_tokens)


def yuan_of_weighted(model: str, weighted: int) -> float | None:
    """多少输入当量 token 合多少元 (同上, 假设价)。"""
    return yuan(model, weighted, 0)
