"""模組名稱與導覽用語一致（T86 F3 追加，PM 裁示 2026-11-14）。

使用者是從導覽認識這些功能的，所以宣告檔（module.json）的 `name` 要跟導覽同一套說法：
案件模組＝「案件管理」、採購・庫存・出貨模組＝導覽群組「採購與庫存」。名稱只是顯示文字，模組鍵與權限鍵不動。
觀測點：宣告檔、模組登錄表（模組管理／授權頁／未啟用提示用的名稱）、權限矩陣群組標題、導覽群組標籤。
"""
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EXPECT = {"case": "案件管理", "supply": "採購與庫存"}


def _manifest(key):
    return json.loads((BACKEND / "modules" / key / "module.json").read_text(encoding="utf-8"))


def test_declared_names_follow_the_navigation_vocabulary():
    for key, name in EXPECT.items():
        assert _manifest(key)["name"] == name, key
        assert _manifest(key).get("key", key) == key, "模組鍵沒變"
    groups = {g["key"]: g["label"] for g in json.loads((BACKEND / "core" / "menu_l1.json").read_text(encoding="utf-8"))["groups"]}
    assert groups["supply"] == EXPECT["supply"], "採購與庫存模組名稱＝導覽群組名稱（不一致就是有人只改了一邊）"


def test_registry_and_matrix_show_the_same_names(client, make_user):
    from core import registry
    states = {s["key"]: s["name"] for s in registry.module_states()}
    for key, name in EXPECT.items():
        assert states.get(key) == name, f"模組登錄表名稱：{key} → {states.get(key)}"
    u, p = make_user(username="mn_sa", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    caps = client.get("/api/permmatrix/matrix", headers=h).json()["caps"]
    titles = {c["unit"]: c["unitLabel"] for c in caps}
    for key, name in EXPECT.items():
        assert titles.get(key) == name, f"權限矩陣群組標題：{key} → {titles.get(key)}"
