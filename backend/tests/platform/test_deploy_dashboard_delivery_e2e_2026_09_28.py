# -*- coding: utf-8 -*-
"""瀏覽器端對端：部署儀表板「6. 套用更新」（UPDATE-DELIVERY §3／§4；A，2026-09-28）。

儀表板以 uvicorn 起在本機（它自己的 app，有「只限本機」middleware）；「本機 ERP」指到測試用的 live_server，
帳密驗證是真的登入一次（最高管理員）。apply_update 不真的跑：delivery._run_powershell 換成假執行器（照 §9.2 寫 result.json）。
交付資料夾、安裝目錄、staging 都是 tmp；不碰正式機與真的雲端資料夾。
觀測點：畫面上的確認內容與結果（DOM）、交付資料夾 results\\ 的結果檔、安裝目錄的 tools 已換上包裡的版本。
"""
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_deploy_dashboard_delivery_2026_09_28 import (  # noqa: E402
    COMMIT, D, PS1, _keys, dd, fake_run, make_install, make_package)


@pytest.fixture()
def dashboard(tmp_path, monkeypatch, live_server):
    import uvicorn
    from tests._ports import free_safe_port
    priv, pub = _keys()
    root = tmp_path / "交付"
    root.mkdir()
    install = make_install(tmp_path)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    monkeypatch.setattr(D, "_default_resolver", lambda: str(root))
    monkeypatch.setattr(D, "verify_package_cmd", lambda *a: [sys.executable, "-c", "pass"])
    monkeypatch.setattr(D, "_run_powershell", fake_run(install))
    monkeypatch.setattr(dd, "DELIVERY_INSTALL_ROOT", install)
    monkeypatch.setattr(dd, "DELIVERY_STAGING_ROOT", tmp_path / "staging")
    monkeypatch.setattr(dd, "_delivery_state", {"prepared": {}, "running": False, "last": None})
    monkeypatch.setenv("MOTRIX_DELIVERY_ERP_URL", live_server)
    name = D.publish(str(make_package(tmp_path, [{"module": "系統設定/儲存位置", "version": "2026-09-28a", "content": "新頁"}])),
                     str(root), priv, now=datetime(2026, 9, 28, 3, 0, 0))
    port = free_safe_port()
    server = uvicorn.Server(uvicorn.Config(dd.app, host="127.0.0.1", port=port, log_level="warning", ws="none"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "儀表板沒有起來"
    try:
        yield {"base": "http://127.0.0.1:%d" % port, "root": root, "install": install, "name": name}
    finally:
        server.should_exit = True
        t.join(timeout=10)


@pytest.mark.e2e
def test_apply_from_the_dashboard_end_to_end(dashboard, make_user, new_context):
    user, pw = make_user(username="dl_e2e_sa", role="superadmin")
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(dashboard["base"] + "/")
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"dl-pkg\"] option').length === 1", timeout=20000)
    assert dashboard["root"].name in page.text_content('[data-testid="dl-root"]')
    page.click('[data-testid="dl-prepare"]')
    page.locator('[data-testid="dl-confirm"]').wait_for(state="visible", timeout=20000)
    text = page.text_content('[data-testid="dl-confirm-text"]')
    assert COMMIT[:8] in text and "系統設定/儲存位置" in text and "無法試算" in text, text
    # 錯的密碼 ⇒ 沒開始，畫面說原因
    page.fill('[data-testid="dl-user"]', user)
    page.fill('[data-testid="dl-pass"]', "wrong-password")
    page.check('[data-testid="dl-ack"]')
    page.click('[data-testid="dl-apply"]')
    page.wait_for_function("() => /沒有開始套用/.test(document.querySelector('[data-testid=\"dl-result\"]').textContent)",
                           timeout=20000)
    assert not (dashboard["root"] / "results").exists()
    # 對的帳密 ⇒ 套用 ⇒ 結果
    page.fill('[data-testid="dl-pass"]', pw)
    page.click('[data-testid="dl-apply"]')
    page.locator('[data-testid="dl-result"][data-outcome="succeeded"]').wait_for(timeout=30000)
    assert "成功" in page.text_content('[data-testid="dl-result"]')
    back = json.loads((dashboard["root"] / "results" / (dashboard["name"] + ".result.json")).read_text(encoding="utf-8"))
    assert back["outcome"] == "succeeded" and back["commit"] == COMMIT
    assert (dashboard["install"] / "backend" / "tools" / "apply_update.ps1").read_bytes() == PS1.encode("utf-8")
    page.wait_for_function("() => /success/.test(document.querySelector('[data-testid=\"dl-last\"]').textContent)", timeout=10000)
    assert page.input_value('[data-testid="dl-pass"]') == "", "密碼送出後清掉"
    assert not errors, errors
