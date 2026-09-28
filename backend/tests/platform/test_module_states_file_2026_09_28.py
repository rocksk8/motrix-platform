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
    assert got == want, "狀態檔與 registry.module_states() 不一致"
    assert len(data["modules"]) == len(registry.module_states()), "一個模組一列"
    # 〔更正（第二十班 core-only 交會紅）：原寫 `assert want and …`——核心版沒有 L2 時 want 本來就是空的；這一題驗的是 L1 寫檔（不可以標 requires_module，§G5 #7），改成只要與 registry 一致〕
    assert not list(tmp_path.rglob("*.tmp")), "先寫 .tmp 再改名：成功後不可以留 .tmp"


def test_write_failure_is_a_warning_not_a_crash(tmp_path, caplog):
    from core import loader
    blocker = tmp_path / "logs"
    blocker.write_text("不是資料夾", encoding="utf-8")          # 目錄位置被一個檔佔住 ⇒ 寫不進去
    assert loader._write_module_states(blocker / "module_states.json") is False
    assert any("寫模組載入狀態檔失敗" in r.getMessage() for r in caplog.records)


def test_main_writes_states_outside_scheduler_gate_unless_pytest():
    """〔更正（稽核 D DB5-S1）：原題要求寫在排程閘門內——以 DISABLE_SCHEDULERS 啟動的安裝（演練）就沒有狀態檔，
    健檢會誤判成「模組沒載入」。改為：不在任何 MOTRIX_DISABLE_SCHEDULERS 的 if 裡；只以「pytest 不在 sys.modules」為條件；
    位置在 mount_modules 之後（載入結果已定）〕"""
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "_write_module_states"]
    assert len(calls) == 1, "main.py 應該恰好一處寫模組載入狀態檔"
    node, guards = calls[0], []
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.If):
            guards.append(ast.dump(node.test))
    assert not any("MOTRIX_DISABLE_SCHEDULERS" in g for g in guards), "不可以綁排程閘門（DB5-S1）"
    assert any("pytest" in g for g in guards), "要以「不在 pytest 之下」為條件（測試 session 不寫進 repo 的 logs/）"
    mount = next(c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "mount_modules")
    assert mount.lineno < calls[0].lineno, "要在 mount_modules 之後（載入結果已定）"


def test_states_file_records_scheduler_flag(tmp_path, monkeypatch):
    """DB5-S1：檔內記 schedulers_disabled ⇒ 健檢讀不到新版本時說得出「此安裝以 DISABLE_SCHEDULERS 啟動」。"""
    from core import loader
    monkeypatch.setenv("MOTRIX_DISABLE_SCHEDULERS", "1")
    loader._write_module_states(tmp_path / "s.json")
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["schedulers_disabled"] is True
    monkeypatch.delenv("MOTRIX_DISABLE_SCHEDULERS")
    loader._write_module_states(tmp_path / "s.json")
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["schedulers_disabled"] is False


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
