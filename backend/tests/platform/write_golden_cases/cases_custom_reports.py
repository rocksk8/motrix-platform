# -*- coding: utf-8 -*-
"""T87 B2 自訂報表寫入路由的金標案例（真成功形狀，不是錯誤形狀）。

setup 先把功能開關與分享開關打開，再用 `INSERT OR IGNORE` 放四份固定編號（9101～9104）的報表給 `wg_admin`
（編號固定，案例的路徑才寫得出來；每個案例前都會重跑 setup，所以可重複）。四份各給一支路由用，DELETE 排最後。
分享端點用空名單呼叫（回 `added`／`removed` 的空陣列）：真正的分享、能力與限額規則由 tests/platform/test_custom_reports_shares_t87.py 逐項斷言。

匯出兩支（`POST …/{rid}/export`、`POST …/{rid}/export-pdf`）回的是檔案、不是 JSON，沒有鍵集可記，只能豁免（見 WAIVE）；
匯出的權限、遮罩、稽核與檔案內容由 tests/platform/test_custom_reports_export_t87.py 斷言。
"""
import json

_DEF = {"version": 1, "source": "quotation", "columns": ["quote_no"]}
_STAMP = "2026-11-14T00:00:00"
_IDS = {"put": 9101, "copy": 9102, "shares": 9103, "delete": 9104}


def _setup(conn):
    from helpers import settings_registry as R
    R.publish("custom_reports", {"enabled": 1, "sharing": 1}, reason="金標案例", user="wg_admin", conn=conn)
    R.invalidate()
    for what, rid in _IDS.items():
        conn.execute(
            "INSERT OR IGNORE INTO custom_reports (id, username, name, source_id, definition_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (rid, "wg_admin", "金標-" + what, "quotation", json.dumps(_DEF, ensure_ascii=False), _STAMP, _STAMP))


CASES = [
    {"key": "POST /api/custom-reports/preview", "url": "/api/custom-reports/preview", "body": dict(_DEF), "setup": _setup},
    {"key": "POST /api/custom-reports", "url": "/api/custom-reports", "body": {"name": "金標-新增", "definition": dict(_DEF)}, "setup": _setup},
    {"key": "PUT /api/custom-reports/{rid}", "url": "/api/custom-reports/%d" % _IDS["put"],
     "body": {"name": "金標-改名", "definition": dict(_DEF)}, "setup": _setup,
     "headers": {"If-Match": _STAMP}},               # etag＝updated_at（見 report_store.etag_of）
    {"key": "POST /api/custom-reports/{rid}/copy", "url": "/api/custom-reports/%d/copy" % _IDS["copy"], "body": {}, "setup": _setup},
    {"key": "POST /api/custom-reports/{rid}/shares", "url": "/api/custom-reports/%d/shares" % _IDS["shares"],
     "body": {"add": [], "remove": []}, "setup": _setup},
    {"key": "DELETE /api/custom-reports/{rid}", "url": "/api/custom-reports/%d" % _IDS["delete"], "body": None, "setup": _setup},
]
WAIVE = {
    "POST /api/custom-reports/{rid}/export": "回應是 xlsx 檔案（不是 JSON）：沒有鍵集可記；權限、遮罩、稽核與檔案內容由 test_custom_reports_export_t87 斷言",
    "POST /api/custom-reports/{rid}/export-pdf": "回應是 PDF 檔案（xlsx 的姊妹，同一個處理函式；不是 JSON）：沒有鍵集可記；同上，另受公司資料第二道閘門",
}
