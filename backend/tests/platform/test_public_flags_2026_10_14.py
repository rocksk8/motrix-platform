# -*- coding: utf-8 -*-
"""public-flags.js：一次讀多個公開設定群組；某個群組讀不到（hidden／未登錄 404、敏感 403）不拖垮其他旗標。
node 真的執行 + 真的端點（GET /api/settings-center/public 對 hidden 群組整個回 404 是既有行為，這裡鎖住不變）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "public-flags.js"
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 'tk' }) } }
const urls = []
const GOOD = { builder_layout: { suppliers: true }, builder_custom_fields: { enabled: true }, builder_actions: { enabled: false } }
let BAD = JSON.parse(process.argv[2])        // 讓哪些群組讀不到
global.fetch = async (url) => {
  urls.push(String(url))
  const names = String(url).split('groups=')[1].split(',')
  if (names.some(n => BAD.includes(n))) return { ok: false, status: 404, json: async () => ({}) }
  const groups = {}; names.forEach(n => { groups[n] = GOOD[n] })
  return { ok: true, status: 200, json: async () => ({ groups }) }
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const out = await window.MotrixPublicFlags.read(['builder_layout', 'builder_custom_fields', 'builder_actions'])
  console.log(JSON.stringify({ out, urls }))
})()
"""


def _run(bad):
    r = subprocess.run([NODE, "-e", HARNESS, str(JS), json.dumps(bad)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_all_readable_is_one_request_with_the_same_url_as_before():
    r = _run([])
    assert r["urls"] == ["/api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_actions"]
    assert r["out"]["builder_layout"] == {"suppliers": True}


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_one_unreadable_group_does_not_kill_the_others():
    r = _run(["builder_actions"])
    assert r["out"] == {"builder_layout": {"suppliers": True}, "builder_custom_fields": {"enabled": True}}   # 版面旗標仍讀得到
    assert len(r["urls"]) == 1 + 3                       # 合併請求失敗 ⇒ 逐組各一個
    r = _run(["builder_layout", "builder_custom_fields", "builder_actions"])
    assert r["out"] == {}                                # 全部讀不到 ⇒ 空物件（呼叫端當旗標關閉），不丟例外


def test_endpoint_keeps_its_strict_behaviour_for_existing_callers(client, make_user):
    """端點本身不變：群組不存在 ⇒ 整個 404（既有行為，頁面自己做逐組退路）；存在的群組照回。"""
    u, p = make_user(username="pf_sales", role="sales")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/settings-center/public?groups=builder_layout", headers=h).status_code == 200
    assert client.get("/api/settings-center/public?groups=builder_layout,no_such_group", headers=h).status_code == 404
    both = client.get("/api/settings-center/public?groups=builder_layout,builder_custom_fields", headers=h)
    assert both.status_code == 200 and set(both.json()["groups"]) == {"builder_layout", "builder_custom_fields"}
