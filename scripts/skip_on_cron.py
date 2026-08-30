#!/usr/bin/env python3
"""这个项目在【夜间 cron】里该不该被跳过? —— 给 daily-sync.yml 的 bash 循环用。

    python skip_on_cron.py <project_id>
      exit 0 = 跳过(on_demand + 确实是 cron)
      exit 1 = 照跑
      exit 2 = 判不了(mapping 读不出来等)—— 调用方应当【照跑】, 不要静默跳过

为什么要有这个文件, 而不是在 bash 里写一句 yaml 判断:
    判据必须是【一份】。sync 那一步用的是 _common.skip_on_demand_on_cron;
    essence 那一步如果自己在 bash 里重写一遍 `grep on_demand`, 两处迟早漂开 ——
    而漂开的表现是"某一步悄悄多跑了一批没验证过的表", 没有任何症状。
    D-047 之前就是这么漏的: 入库那步有闸, essence 那步没有。

exit 2 的取向: 判不了时【照跑】而不是【跳过】。跳过是静默少干活, 查起来毫无线索;
照跑最多是多标了一批(幂等, 且下游本来就要人审)。宁可吵不可静。
"""
from __future__ import annotations

import os
import sys

from _common import load_mapping, setup_logger, skip_on_demand_on_cron

logger = setup_logger("skip_on_cron")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        logger.error("用法: python skip_on_cron.py <project_id>")
        return 2
    project_id = args[0]
    scheduled = os.environ.get("TV_SCHEDULED_RUN") == "true"
    try:
        mapping = load_mapping(project_id)
    except Exception as exc:                       # noqa: BLE001 —— 判不了就照跑
        logger.warning("读不出 %s 的 mapping(%s) → 判不了, 按【照跑】处理", project_id, exc)
        return 2
    sync_interval = (mapping.get("sync_config") or {}).get("sync_interval")
    return 0 if skip_on_demand_on_cron(sync_interval, scheduled) else 1


if __name__ == "__main__":
    sys.exit(main())
