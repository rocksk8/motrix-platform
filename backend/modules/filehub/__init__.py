# -*- coding: utf-8 -*-
"""檔案中心（附件目錄 P3）。只 import core／helpers／db（L1），不 import 其他 L2 模組：搜尋走 `attachments.catalog` 提供者。"""
from core.registry import ModuleSpec

from modules.filehub import api

MODULE = ModuleSpec(
    key="filehub",
    routers=[api.router],
)
