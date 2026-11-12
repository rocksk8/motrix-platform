# -*- coding: utf-8 -*-
"""T80c 外勤手機 S1：補案件留言附件（multipart）的寫入類路由金標案例。
`POST /api/quotations/{quote_no}/updates/{uid}/files`——setup 先種一張報價單與一則 id 固定的留言，再補一張 1x1 PNG（帶 geo）。
（`record_write` 的 `files` 選填參數就是為這類 multipart 路由加的；沒給 `files` 的案例行為不變。）"""
import base64

# 1x1 PNG（base64：不在原始碼裡放二進位跳脫）
_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==")


def _setup(conn):
    conn.execute(
        "INSERT OR IGNORE INTO quotations (quote_no, customer_name, project_name, status, deal_tag, total, data_json, created_at, updated_at) "
        "VALUES ('WG-FIELD-1','金標客戶','金標案件','已送出','已成案',1000,'{\"dealTag\": \"已成案\"}','2026-01-01T00:00:00','2026-01-01T00:00:00')")
    conn.execute(
        "INSERT OR IGNORE INTO case_updates (id, quote_no, author, content, type, created_at, files_json) "
        "VALUES (900001,'WG-FIELD-1','golden','金標留言','comment','2026-01-01T00:00:00','[]')")


CASES = [
    {"key": "POST /api/quotations/{quote_no}/updates/{uid}/files",
     "url": "/api/quotations/WG-FIELD-1/updates/900001/files",
     "body": {"geo": "25.033,121.5654,10"},
     "files": [("files", ("g.png", _PNG, "image/png"))],
     "setup": _setup},
]
WAIVE = {}
