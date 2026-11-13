# -*- coding: utf-8 -*-
"""匯入精靈（T85）。只 import core／helpers／db（L1），不 import 其他 L2 模組。

無狀態：範本下載與檔案解析；實際寫入走 L1 既有的 `/api/customers/import-rows`、`/api/parts/import-rows`、`/api/users/import-rows`。
"""
from core.registry import ModuleSpec

from modules.importer import api

MODULE = ModuleSpec(
    key="importer",
    routers=[api.router],
)
