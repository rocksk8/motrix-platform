# -*- coding: utf-8 -*-
"""產品的 Edge PDF 重用專屬 profile（使用者 2026-09-30：「盡可能降低硬碟的重複寫入」）。

原本每次 `msedge --headless` 都不帶 `--user-data-dir`，Edge 每次建一份全新 profile（抽樣寫 374 MB、PDF 本身 3.5 MB）。
現在 `helpers/startup.run_edge_pdf` 自己拿專屬 profile（`<LOGS_DIR>/edge_profiles/p1..pN`）：
① 依序呼叫重用同一份 ② 併發（上限內）各拿不同份 ③ 逾時被殺／非 0 結束 ⇒ 整份刪掉、下次重建 ④ 定期量大小、過大重建
⑤ 拿不到專屬目錄 ⇒ 退回舊行為（不帶旗標） ⑥ 呼叫端已帶 `--user-data-dir`（測試端池）⇒ 不動 ⑦ 命令其餘部分不變。
用假的 `subprocess.run`（不真的開 Edge）；真實量測見回報。
"""
import os
import subprocess
import threading
import time

import pytest

import helpers.startup as startup


@pytest.fixture
def prod(monkeypatch, tmp_path):
    """乾淨的產品 profile 池（根目錄導到 tmp）＋假的 subprocess.run（記錄命令、往 profile 寫一個檔模擬快取）。"""
    root = tmp_path / "edge_profiles"
    monkeypatch.setattr(startup, "EDGE_PROFILE_ROOT", str(root))
    monkeypatch.setattr(startup, "_EDGE_PROFILE_POOL", [])
    monkeypatch.setattr(startup, "_EDGE_PROFILE_STATE", {"init": False, "runs": 0})
    st = {"seen": [], "delay": 0.0, "rc": 0, "raise": None, "lock": threading.Lock()}

    def fake_run(cmd, **kw):
        d = next((a.split("=", 1)[1] for a in cmd if str(a).startswith("--user-data-dir=")), None)
        with st["lock"]:
            st["seen"].append(list(cmd))
        if d:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "cache.bin"), "ab") as f:
                f.write(b"x" * 1024)
        time.sleep(st["delay"])
        if st["raise"]:
            raise st["raise"]
        return subprocess.CompletedProcess(cmd, st["rc"])
    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    monkeypatch.setattr(startup, "EDGE_PDF_SEMAPHORE", threading.BoundedSemaphore(startup.EDGE_PDF_MAX_CONCURRENCY))
    st["root"] = root
    return st


def _dir_of(cmd):
    return next(a.split("=", 1)[1] for a in cmd if str(a).startswith("--user-data-dir="))


def test_sequential_runs_reuse_the_same_profile_and_keep_the_command_intact(prod):
    for i in range(4):
        startup.run_edge_pdf(["msedge.exe", "--headless", "--print-to-pdf=x%d.pdf" % i, "file:///a.html"])
    dirs = [_dir_of(c) for c in prod["seen"]]
    assert all(d.startswith(str(prod["root"])) for d in dirs), "profile 必須在專屬根目錄底下"
    for i, c in enumerate(prod["seen"]):
        assert c[0] == "msedge.exe" and c[2:] == ["--headless", "--print-to-pdf=x%d.pdf" % i, "file:///a.html"], c
    # 依序呼叫（每次用完就歸還）⇒ 一直是同一批目錄輪流用，不是每次新開；累積的快取檔證明被重用
    assert len(set(dirs)) <= startup.EDGE_PDF_MAX_CONCURRENCY
    reused = max(set(dirs), key=dirs.count)
    assert dirs.count(reused) >= 2 or len(set(dirs)) == len(dirs) and len(dirs) <= startup.EDGE_PDF_MAX_CONCURRENCY
    assert os.path.getsize(os.path.join(reused, "cache.bin")) >= 1024


def test_concurrent_runs_within_the_limit_get_different_profiles(prod):
    prod["delay"] = 0.3
    n = startup.EDGE_PDF_MAX_CONCURRENCY
    ts = [threading.Thread(target=startup.run_edge_pdf, args=(["msedge.exe", "--headless", "u%d" % i],)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    dirs = [_dir_of(c) for c in prod["seen"]]
    assert len(dirs) == n and len(set(dirs)) == n, "同時在跑的 Edge 共用了 profile：%s" % dirs


def test_a_timeout_discards_the_profile_and_it_is_rebuilt_next_time(prod):
    prod["raise"] = subprocess.TimeoutExpired("msedge", 1)
    startup.run_edge_pdf(["msedge.exe", "--headless", "a"])                # 不往外丟例外
    d = _dir_of(prod["seen"][0])
    assert not os.path.exists(d), "逾時被殺的 profile 可能留鎖／壞檔，要整份刪掉"
    prod["raise"] = None
    for _ in range(startup.EDGE_PDF_MAX_CONCURRENCY):                      # 輪一圈一定會再拿到那一份
        startup.run_edge_pdf(["msedge.exe", "--headless", "b"])
    assert os.path.isdir(d), "刪掉的 profile 下次要能重建並可用"


def test_a_nonzero_exit_discards_the_profile(prod):
    prod["rc"] = 1
    startup.run_edge_pdf(["msedge.exe", "--headless", "a"])
    assert not os.path.exists(_dir_of(prod["seen"][0]))


def test_an_oversized_profile_is_rebuilt_on_the_periodic_check(prod, monkeypatch):
    monkeypatch.setattr(startup, "EDGE_PROFILE_MAX_BYTES", 1500)
    monkeypatch.setattr(startup, "EDGE_PROFILE_CHECK_EVERY", 1)
    startup.run_edge_pdf(["msedge.exe", "--headless", "a"])                # 1 KB：未超過
    d = _dir_of(prod["seen"][0])
    assert os.path.isdir(d)
    for _ in range(startup.EDGE_PDF_MAX_CONCURRENCY):                      # 輪一圈回到同一份，累積超過上限
        startup.run_edge_pdf(["msedge.exe", "--headless", "b"])
    sizes = [os.path.getsize(os.path.join(d, "cache.bin"))] if os.path.exists(os.path.join(d, "cache.bin")) else [0]
    assert sizes[0] <= 1500 + 1024, "過大的 profile 沒有重建（%s）" % sizes


def test_falls_back_to_the_old_behaviour_when_the_dedicated_dir_is_unavailable(prod, monkeypatch):
    monkeypatch.setattr(startup.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    startup.run_edge_pdf(["msedge.exe", "--headless", "a"])
    assert prod["seen"][0] == ["msedge.exe", "--headless", "a"], "拿不到專屬目錄時應退回原命令（不帶旗標），功能不受影響"


def test_a_caller_supplied_user_data_dir_is_left_alone(prod, tmp_path):
    other = "--user-data-dir=%s" % (tmp_path / "caller_profile")
    startup.run_edge_pdf(["msedge.exe", other, "--headless", "a"])
    assert prod["seen"][0] == ["msedge.exe", other, "--headless", "a"]
    assert not prod["root"].exists(), "呼叫端已指定 ⇒ 不該再開專屬目錄"


def test_profile_root_is_separate_from_the_users_own_edge_profile():
    assert os.path.normcase(startup.EDGE_PROFILE_ROOT).endswith(os.path.normcase(os.path.join("logs", "edge_profiles")))
    user_edge = os.path.normcase(os.path.join(os.environ.get("LOCALAPPDATA", "C:\\nowhere"), "Microsoft", "Edge"))
    assert not os.path.normcase(startup.EDGE_PROFILE_ROOT).startswith(user_edge)
