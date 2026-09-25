# -*- coding: utf-8 -*-
"""M11 標案雷達。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec, RuntimeSwitch

from modules.tender_radar import api, source


def _radar_notice():
    # 只記「開著」那一側：不小心開著而沒人知道才是安靜的錯（原 main.py 的理由照舊）
    if source.radar_on():
        return "MOTRIX_TENDER_RADAR=1 —— 標案雷達已開，這台機器會對外連線（政府電子採購網）"
    return None


MODULE = ModuleSpec(
    key="tender_radar",
    routers=[api.router],
    # 走模組屬性、晚綁定：直接放函式物件會凍結成副本，測試 patch 不到（test_s5 抓到過）
    schedulers=[lambda: source.schedule_tender_scan()],
    startup_notices=[_radar_notice],
    runtime_switches=[RuntimeSwitch("MOTRIX_TENDER_RADAR", "標案雷達（連政府電子採購網）",
                                    lambda: source.radar_on())],
)
