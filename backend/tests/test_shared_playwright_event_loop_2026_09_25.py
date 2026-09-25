"""共用瀏覽器不可以讓同一個 worker 之後的 `asyncio.run()` 失敗（2026-09-25 建包）。

☠️ 建包非 e2e 輪（-n 6）紅 15 題，全在 test_upload_path_traversal、全在 gw5：
   「asyncio.run() cannot be called from a running event loop」；單跑該檔 17/17 綠。
   成因：session 級共用的 sync_playwright 開著時，主執行緒上掛著一個執行中的 event loop；
   有 3 題用了共用瀏覽器卻沒標 e2e（netguard 2、shared_fixtures 1），混進非 e2e 輪，
   同一 worker 之後所有 asyncio.run 都失敗 ⇒ 順序相依，只有抽到它們的 worker 中。
🔑 修在 conftest `_pw_coexist`：這一題不經過 new_context ⇒ 開始前先停掉共用的。
   看「用不用」而不是 e2e 標記 ⇒ 下次漏標也不會漏出去（漏標的 3 題另外補標 e2e）。
   驗法：子 pytest、單一行程、固定順序跑 _probe_shared_pw_then_asyncio.py（修前 test_2 紅）。
"""
import os

import pytest

from tests._subproc import run_python, utf8_env

pytest.importorskip("playwright.sync_api")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.e2e
def test_asyncio_run_works_after_a_test_that_used_the_shared_browser(tmp_path):
    """① 用共用瀏覽器（沒標 e2e）② asyncio.run ③ 共用瀏覽器被停掉之後還能再起來。"""
    proc = run_python(["-m", "pytest", os.path.join("tests", "_probe_shared_pw_then_asyncio.py"), "-q",
                       "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:xdist",
                       f"--basetemp={tmp_path / 'probe'}"],
                      cwd=BACKEND, env=utf8_env(), timeout=240)
    assert "3 passed" in proc.stdout, "共用瀏覽器之後的 asyncio.run 失敗，或停掉後起不來：\n" + proc.stdout[-2000:]
