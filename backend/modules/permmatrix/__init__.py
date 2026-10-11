# -*- coding: utf-8 -*-
"""權限矩陣（資料與寫入）。只 import core／helpers／db（L1），不 import 其他 L2 模組。

設計：docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md。判斷在 L1 `helpers/perm.py`（矩陣來源缺席時用 legacy 種子＝今天的行為）；
本模組提供矩陣的**資料**（覆寫列、個人覆寫、代理、24 小時待生效、版本），透過提供者 `perm.matrix_source` 交給 L1。
"""
import importlib

from core.registry import ModuleSpec

from modules.permmatrix import service

#: 模組自己的 migration（檔名以版號開頭，不是合法的 import 名稱 ⇒ importlib）
_m0001 = importlib.import_module("modules.permmatrix.migrations.0001_permission_matrix")

MODULE = ModuleSpec(
    key="permmatrix",
    routers=[],
    migrations=[(1, _m0001.up)],
    providers={("perm.matrix_source", "permmatrix"): service.load_matrix},      # 字面字串：整合點登記表守門只認字面值
)
