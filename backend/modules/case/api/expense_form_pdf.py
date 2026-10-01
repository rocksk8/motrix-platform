# -*- coding: utf-8 -*-
"""費用單據（kind<>''）的輸出：`GET /api/quotations/{quote_no}/extra-expenses/{id}/document?format=html|pdf`（A2-7，2026-10-01）。

版型來自單據**釘住的定義版本**（`def_version`；定義之後改版，舊單據仍用自己的版型）的 `output.template`；
渲染走 L1 `helpers.doc_render.render_document`（公司抬頭／頁尾／簽核欄／未核可每頁紅色標示都由它負責，版型不能關掉標示）。
可見性＝本單的建立者、簽核鏈成員、admin／superadmin、出納／財務（單據含金額，其他人看不到——與列表可見規則一致）。
`kind=''` 的舊額外支出沒有版型 ⇒ 404（維持今天的行為）。
"""
import json

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from db import get_db
from helpers.auth import _require_user
from modules.case.api import case_extra_expenses as X

router = APIRouter()

#: 已核准以外一律視為「尚未核可」（草稿、待審核、簽核中、已駁回）
_APPROVED = ("已核准",)


def _names(conn, table, ids, col):
    """{id字串: 顯示名稱}；查不到的留原值（不丟資料）。"""
    out = {}
    for i in ids:
        r = conn.execute("SELECT %s AS n FROM %s WHERE %s=?" % (col, table, "username" if table == "users" else "id"), (i,)).fetchone() \
            if i not in ("", None) else None
        out[str(i)] = (r["n"] if r and r["n"] else str(i))
    return out


def build_view(conn, row, body: dict) -> dict:
    """單據視圖（doc_render 的約定鍵＋`fields.<key>`）。ref 欄位轉成可讀名稱；明細保留所有鍵；合計取 `total_cost`（後端權威）。"""
    data = json.loads(row["data_json"] or "{}") if row["data_json"] else {}
    lines = json.loads(row["lines_json"] or "[]") if row["lines_json"] else []
    fields = dict(data)
    for f in body.get("fields") or []:
        k = f.get("key")
        if f.get("type") == "ref" and k in fields and fields[k] not in ("", None):
            if f.get("target") == "users":
                fields[k] = _names(conn, "users", [fields[k]], "COALESCE(NULLIF(display_name,''), username)")[str(fields[k])]
            elif f.get("target") == "departments":
                fields[k] = _names(conn, "departments", [fields[k]], "name")[str(fields[k])]
        elif f.get("type") == "daterange" and isinstance(fields.get(k), dict):
            v = fields[k]
            fields[k] = "%s ～ %s" % (v.get("from", ""), v.get("to", ""))
    rows = []
    for l in lines:
        r = dict(l)
        r["category"] = l.get("categoryName") or l.get("category") or ""
        rows.append(r)
    fields["lines"] = rows
    fields["total"] = int(round(float(row["total_cost"] or 0)))
    try:
        approval = json.loads(row["approval_json"] or "{}") or {}
    except (TypeError, ValueError):
        approval = {}
    status = row["status"] or ""
    return {"recordNo": row["doc_code"], "status": status, "statusLabel": status, "unapproved": status not in _APPROVED,
            "createdBy": row["created_by"] or "", "approval": approval, "fields": fields, **fields}


@router.get("/api/quotations/{quote_no}/extra-expenses/{exp_id}/document")
def expense_document(quote_no: str, exp_id: int, format: str = Query("html"), authorization: str = Header(None)):
    user = _require_user(authorization)
    qn = X._qn(quote_no)
    conn = get_db()
    try:
        X._guard_case(conn, qn, user)
        row = conn.execute("SELECT * FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, qn)).fetchone()
        if not row or not (row["kind"] or "") or not X._caseless_visible(conn, row, user):      # 看不到＝不存在
            raise HTTPException(404, "找不到這張費用單據")
        from helpers import expense_types as ET
        dv = int(row["def_version"] or 0)
        # def_version=0 ＝ W2 還沒把版本釘在列上（或單據用程式預設）⇒ 用目前生效版（沒有發布版時就是程式預設）
        t = ET.get_type(conn, row["kind"], dv if dv > 0 else None)
        if t is None:
            raise HTTPException(404, "找不到這張單據的類型定義")
        template = (t["body"].get("output") or {}).get("template")
        if not template:
            raise HTTPException(404, "這個類型沒有輸出版型")
        view = build_view(conn, row, t["body"])
        from helpers.doc_render import render_document
        html = render_document(template, view)
    finally:
        conn.close()
    if format == "pdf":
        import pdf_gen
        return Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="%s.pdf"' % view["recordNo"]})
    return HTMLResponse(html)
