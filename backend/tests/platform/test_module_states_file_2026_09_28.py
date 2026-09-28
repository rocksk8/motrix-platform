"""B55 S2（L1）：模組載入狀態檔與單模組覆蓋紀錄的分類（設計 docs/platform/MODULE-UPDATE-DELIVERY.md §1.3 步驟 9、§3）。

- `core.loader._write_module_states`：健檢讀的機器可讀狀態（稽核 D DB-S4）
- main.py 在排程閘門內呼叫它（正式機與演練一律開著；測試 session 不寫進 repo）
- loader 兩個 log 字串是健檢第二道的契約
- `.deployed_modules.json` 分類＝config（稽核 D DB-O1）：完整包刪除計畫與 cleanup-snapshot 不碰它
"""
import ast
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"


def test_states_file_matches_registry(client, tmp_path):
    from core import loader, registry
    target = tmp_path / "logs" / "module_states.json"
    assert loader._write_module_states(target) is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert data["started_at"]
    want = {s["key"]: (s["state"], s.get("version")) for s in registry.module_states()}
    got = {m["key"]: (m["state"], m["version"]) for m in data["modules"]}
    assert want and got == want, "狀態檔與 registry.module_states() 不一致"
    assert not list(tmp_path.rglob("*.tmp")), "先寫 .tmp 再改名：成功後不可以留 .tmp"


def test_write_failure_is_a_warning_not_a_crash(tmp_path, caplog):
    from core import loader
    blocker = tmp_path / "logs"
    blocker.write_text("不是資料夾", encoding="utf-8")          # 目錄位置被一個檔佔住 ⇒ 寫不進去
    assert loader._write_module_states(blocker / "module_states.json") is False
    assert any("寫模組載入狀態檔失敗" in r.getMessage() for r in caplog.records)


def test_main_writes_states_inside_scheduler_gate_after_start_schedulers():
    """AST（註解不在 AST 裡）：`if MOTRIX_DISABLE_SCHEDULERS` 區塊裡、start_schedulers 之後呼叫 _write_module_states。"""
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    blocks = [n for n in ast.walk(tree) if isinstance(n, ast.If) and "MOTRIX_DISABLE_SCHEDULERS" in ast.dump(n.test)
              and any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "start_schedulers" for c in ast.walk(n))]
    assert len(blocks) == 1, "找不到（或不只一個）啟動模組排程的閘門區塊"
    calls = [getattr(c.func, "attr", getattr(c.func, "id", "")) for s in blocks[0].body for c in ast.walk(s)
             if isinstance(c, ast.Call)]
    assert "_write_module_states" in calls, "排程閘門內沒有寫模組載入狀態檔"
    assert calls.index("start_schedulers") < calls.index("_write_module_states")


def test_loader_log_strings_are_a_contract():
    """健檢第二道讀 server.log 的這兩行；改字串 ⇒ 這一題紅 ⇒ 同步改 apply_module_update.ps1。"""
    src = (BACKEND / "core" / "loader.py").read_text(encoding="utf-8")
    assert 'logger.info("模組 %s %s 已載入", name, manifest.get("version", "?"))' in src
    assert 'logger.error("模組 %s 未載入：%s", name, e)' in src


def test_deployed_modules_file_is_config():
    from core import upgrade
    rel = "backend/.deployed_modules.json"
    assert rel in upgrade.CONFIG_FILES
    assert upgrade.classify(rel) == "config", "覆蓋紀錄要與 .deployed_commit.json 同類（DB-O1）"
    assert upgrade.classify("backend/.deployed_commit.json") == "config"


def test_apply_plan_never_deletes_deployed_modules_file():
    """完整包的刪除計畫只刪 classify==program ⇒ config 的覆蓋紀錄不會被刪（cleanup-snapshot 同一支 deletable）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_apply_plan", BACKEND / "tools" / "apply_plan.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    from core import upgrade
    assert not ap.deletable("backend/.deployed_modules.json", upgrade)
    assert ap.deletable("backend/modules/tender_radar/source.py", upgrade), "正對照：程式檔要可刪"
