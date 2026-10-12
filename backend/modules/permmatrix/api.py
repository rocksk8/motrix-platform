# -*- coding: utf-8 -*-
"""權限矩陣的唯讀狀態探針（D7 final_drill 要求每個模組宣告 provides.probes）。

只回固定欄位；不讀 perm_* 表、不碰任何權限判斷。矩陣的寫入端點與頁面仍未接線（SPEC PMX14）。
"""
import json
from pathlib import Path

from fastapi import APIRouter, Header

from helpers import _require_user

router = APIRouter()

_MANIFEST = Path(__file__).with_name("module.json")


def _version() -> str:
    try:
        return str(json.loads(_MANIFEST.read_text(encoding="utf-8")).get("version") or "")
    except Exception:                                                       # noqa: BLE001
        return ""


@router.get("/api/permmatrix/status")
def permmatrix_status(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ok": True, "module": "permmatrix", "version": _version()}
