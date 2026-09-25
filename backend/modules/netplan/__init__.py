# -*- coding: utf-8 -*-
"""M10 網路規劃（網路架構規劃書、快速拓樸）。只 import core／helpers／db（L1），不 import 其他 L2 模組。
與案件（M01）的關係經 IP-11 `case.access`：M01 不在時規劃書照常建立與編輯，只是不能綁定案件。"""
from core.registry import ModuleSpec

from modules.netplan import api

# 規劃書與快速拓樸都在 api.py 的同一支 router（守門的端點掃描只認 api.py 的 `router`；dep_scan 只看模組第一層）
MODULE = ModuleSpec(key="netplan", routers=[api.router])
