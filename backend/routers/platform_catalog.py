# -*- coding: utf-8 -*-
"""能力目錄端點（CUSTOMIZATION-SPEC P1）：`GET /api/platform/catalog`，僅超級管理員、唯讀。

內容由 `core.catalog.build()` 收集；本檔只負責權限與把 L1 輸出引擎登記成 `outputs` 區段
（輸出引擎是 L1 helper，core 不 import helpers）。
"""
import os

from fastapi import APIRouter, Header

from core import catalog
from helpers import _require_user
from helpers import doc_template

router = APIRouter()


def _outputs():
    """輸出引擎（P2）：主題、積木、隨程式出貨的預設版型。格式（format）沒有公開常數 ⇒ 不列（見 gaps）。"""
    d = doc_template._TEMPLATE_DIR                              # noqa: SLF001 預設版型目錄的唯一定義
    templates = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".json"):
            key = name[:-5]
            t = doc_template.load_default(key)
            templates.append({"key": key, "version": t.get("version"), "theme": t.get("theme"),
                              "title": (t.get("title") or {}).get("suffix", "").strip()})
    return {"themes": sorted(doc_template.THEMES), "blocks": sorted(doc_template.BLOCKS), "templates": templates,
            "formats": None, "formatsNote": "格式目錄寫在 doc_template._fmt 內、沒有公開常數；公開後改由這裡列出"}


catalog.register_section("outputs", "helpers.doc_template", _outputs)


@router.get("/api/platform/catalog")
def get_platform_catalog(authorization: str = Header(None)):
    """能力目錄：已載入模組的端點與可自訂點、provider、事件、輸出引擎；缺的區段列在 gaps。"""
    _require_user(authorization, require_superadmin=True)
    return catalog.build()
