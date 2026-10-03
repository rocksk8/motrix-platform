# -*- coding: utf-8 -*-
"""D12 驗證開發機的種子資料（冪等）。用法：python tools/platform/d12_verify_seed.py [port=8870]。
只對本機開發伺服器（127.0.0.1）操作；做三件事：① admin 登入（第一次用 backend/.initial_admin_credentials.txt 的臨時密碼，改成驗證用開發密碼）
② 填一份假的本公司資料並確認（否則寫入類 API 會被「本公司資料未設定」閘門 428 擋住）③ 建「拖放驗證用」模組草稿 d12demo。"""
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8870
BASE = "http://127.0.0.1:%d" % PORT
DEV_PW = "D12-verify-Mouse-2026"
CRED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", ".initial_admin_credentials.txt")


def call(method, path, body=None, tok=None, quiet=False):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        if quiet:
            return {"_http": e.code}
        raise SystemExit("HTTP %s %s %s %s" % (e.code, method, path, e.read().decode("utf-8", "replace")[:300]))


def login():
    r = call("POST", "/api/auth/login", {"username": "admin", "password": DEV_PW}, quiet=True)
    if r.get("token"):
        return r["token"]
    temp = ""
    for line in open(CRED, encoding="utf-8", errors="replace"):
        if line.startswith("臨時密碼:"):
            temp = line.split(":", 1)[1].strip()
    r = call("POST", "/api/auth/login", {"username": "admin", "password": temp})
    call("PATCH", "/api/auth/change-password", {"current_password": temp, "new_password": DEV_PW}, r["token"])
    return call("POST", "/api/auth/login", {"username": "admin", "password": DEV_PW})["token"]


tok = login()
call("PUT", "/api/settings/company-profile", {"name": "開發機測試公司（D12 驗證用）", "tax_id": "04595257", "contact_info": "dev@example.invalid", "confirmIdentity": True}, tok)
lines = {"key": "lines", "label": "費用明細", "type": "table", "dataClass": "T1", "minRows": 0, "maxRows": 200, "addLabel": "新增一列",
         "columns": [{"key": "item", "label": "項目", "type": "text"}, {"key": "qty", "label": "數量", "type": "number"},
                     {"key": "unit_cost", "label": "單價", "type": "number"},
                     {"key": "amount", "label": "小計", "type": "formula", "formula": "round_half_up(qty * unit_cost)"}]}
body = {"name": "拖放驗證用（開發機）", "icon": "", "permission": "custom.d12demo",
        "numbering": {"prefix": "DD", "date": "YYYYMMDD", "digits": 4},
        "fields": [{"key": "place", "label": "地點", "type": "select", "dataClass": "T1", "required": True, "options": ["台北", "台中", "高雄", "海外"]},
                   {"key": "amount", "label": "金額", "type": "number", "dataClass": "T1", "min": 0},
                   {"key": "memo", "label": "備註", "type": "text", "dataClass": "T1"},
                   {"key": "reason", "label": "事由", "type": "text", "dataClass": "T1"},
                   lines,
                   {"key": "total", "label": "總額", "type": "formula", "dataClass": "T1", "formula": "total(lines, \"amount\")"}],
        "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
        "ui": {"form": {"groups": [{"title": "基本資料", "fields": ["place", "amount"]}, {"title": "其他", "fields": ["memo", "reason"]},
                                   {"title": "費用", "fields": ["lines", "total"]}, {"title": "空的區塊（拖進來試試）", "fields": []}]},
               "list": {"columns": ["place", "amount"]}}}
r = call("PUT", "/api/definitions/custom_module/d12demo/draft", {"body": body}, tok)
print("seed ok; module draft problems:", r.get("problems"))
