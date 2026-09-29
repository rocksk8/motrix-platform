# -*- coding: utf-8 -*-
"""附近旅宿（lodging）。只 import core／helpers／db（L1），不 import 其他 L2 模組。

設計與條款：docs/platform/LODGING-NEARBY.md。
"""
import importlib

from core.registry import ModuleSpec, RuntimeSwitch

from modules.lodging import api, api_records, source

#: 模組自己的 migration（檔名以版號開頭，不是合法的 import 名稱 ⇒ importlib）
_m0001 = importlib.import_module("modules.lodging.migrations.0001_lodging_tables")


def _fetch_notice():
    # 只記「開著」那一側：不小心開著而沒人知道才是安靜的錯（同標案雷達）
    if source.fetch_on():
        return ("%s=1 —— 附近旅宿資料下載已開：每日 %d 點後自動更新一次，最高管理者也可按「更新旅宿資料」（連交通部觀光署）"
                % (source.FETCH_ENV, source.DAILY_REFRESH_HOUR))
    return None


MODULE = ModuleSpec(
    key="lodging",
    routers=[api.router, api_records.router],
    migrations=[(1, _m0001.up)],
    schedulers=[lambda: source.schedule_daily_refresh()],
    startup_notices=[_fetch_notice],
    runtime_switches=[RuntimeSwitch(source.FETCH_ENV, "附近旅宿資料下載（連交通部觀光署）",
                                    lambda: source.fetch_on())],
)
