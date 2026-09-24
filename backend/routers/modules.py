# -*- coding: utf-8 -*-
"""權限模組目錄（B7）：`helpers/module_registry.py` 是唯一來源，這支只負責給權限畫面讀。

門檻＝使用者管理頁（sidebar.js 的 `sa`：只有 superadmin）——不比那一頁寬。
"""
from fastapi import APIRouter, Header

from helpers import _require_user
from helpers.module_registry import catalog

router = APIRouter()


@router.get("/api/modules/catalog")
def get_module_catalog(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    return catalog()
