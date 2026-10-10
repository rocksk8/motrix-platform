# -*- coding: utf-8 -*-
"""刪除暫存區（資源回收筒）。只 import core／helpers／db（L1），不 import 其他 L2 模組。

設計：docs/platform/plans/RECYCLE-BIN-DESIGN-T52.md；進度與決定：RECYCLE-BIN-P0-STATE-T53.md。
擁有單據的模組透過 L1 契約 `helpers/recycle_bin.py`（提供 `recyclebin.adapter`、呼叫 `recyclebin.delete`）加入；本模組不認識任何單據。
"""
import importlib

from core.registry import ModuleSpec

from helpers import recycle_bin as RB
from modules.recyclebin import api, jobs, service

#: 模組自己的 migration（檔名以版號開頭，不是合法的 import 名稱 ⇒ importlib）
_m0001 = importlib.import_module("modules.recyclebin.migrations.0001_recycle_bin")

MODULE = ModuleSpec(
    key="recyclebin",
    routers=[api.router],
    migrations=[(1, _m0001.up)],
    schedulers=[lambda: jobs.schedule_daily()],
    providers={(RB.CAP_DELETE, "recyclebin"): service.delete},
)
