# -*- coding: utf-8 -*-
"""附件插槽的端點（BP-4 S2；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §3）。旗標 `builder_slots.enabled` 關閉 ⇒ 全部不給。

- `GET  /api/attachment-slots/catalog`                 僅最高管理者：單據類型、位置代號（唯讀）、硬底線、平台上限（編輯器的下拉）。旗標關閉 ⇒ 404。
- `GET  /api/attachment-slots/{doc_type}`              登入者：這種單據、這位使用者可選的附件種類（已發布定義，依 uploaders 過濾）。
                                                        旗標關閉 ⇒ `{enabled:false, slots:[內建簽回單]}`；不是可宣告的單據類型 ⇒ 404。
- `POST /api/attachment-slots/{doc_type}/simulate`     僅最高管理者、**唯讀**：`{definition, slot, sample:{filename,size,headerHex?,existing?}, docNo?}`
                                                        ⇒ 收不收、存哪（顯示用路徑）、誰能讀（逐角色人數）。不寫檔、不建資料夾。旗標關閉 ⇒ 404。
定義的編輯、發布、還原走既有 `/api/definitions/attachment_slot/doc:<單據類型>/…`（僅最高管理者）。插槽不授權：讀取一律是位置代號的提供者。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import attachment_slots as AS

router = APIRouter()


def _doc_or_404(doc_type):
    if doc_type not in AS.SLOTTED_DOC_TYPES:
        raise HTTPException(404, "這種單據沒有附件種類設定")


@router.get("/api/attachment-slots/catalog")
def get_catalog(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if not AS.enabled():
        raise HTTPException(404, "未開放")
    return AS.catalog()


@router.get("/api/attachment-slots/{doc_type}")
def get_slots(doc_type: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _doc_or_404(doc_type)
    conn = get_db()
    try:
        return {"enabled": AS.enabled(conn), "slots": AS.effective_slots(conn, doc_type, user)}
    finally:
        conn.close()


@router.post("/api/attachment-slots/{doc_type}/simulate")
def simulate_upload(doc_type: str, body: dict = Body(default={}), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _doc_or_404(doc_type)
    if not AS.enabled():
        raise HTTPException(404, "未開放")
    b = body or {}
    if not isinstance(b.get("definition"), dict) or not isinstance(b.get("sample"), dict):
        raise HTTPException(422, "需要 definition 與 sample")
    conn = get_db()
    try:
        return AS.simulate(conn, b["definition"], doc_type, str(b.get("slot") or ""), b["sample"], str(b.get("docNo") or ""))
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0]})
    except LookupError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()
