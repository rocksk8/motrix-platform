# -*- coding: utf-8 -*-
"""附近旅宿：唯一的對外連線（開關、速率、單一執行）、zip 防護（LG-S3）、解析與不存個資欄位。

LODGING-NEARBY.md §3.5、§3.7。觀測點是 `fetch_raw` 的**呼叫次數**（不是「有沒有資料」）：
「沒產生資料」≠「沒連線」。
"""
from datetime import datetime, timedelta

import pytest

from modules.lodging import source as ls
from modules.lodging.tests import _fixtures as fx

T0 = datetime(2026, 9, 28, 17, 0, 0)


@pytest.fixture()
def net(client, monkeypatch):
    """換掉唯一的對外連線；記呼叫次數。預設回一包合法資料。"""
    calls = []
    box = {"blob": fx.good_zip(), "exc": None}

    def fake_fetch(url=ls.DATASET_URL):
        calls.append(url)
        if box["exc"]:
            raise box["exc"]
        return box["blob"]

    monkeypatch.setattr(ls, "fetch_raw", fake_fetch)
    monkeypatch.setattr(ls, "_now", lambda: box.get("now", T0))
    monkeypatch.setenv(ls.FETCH_ENV, "1")
    box["calls"] = calls
    return box


def _catalog():
    return fx.rows("SELECT * FROM lodging_catalog ORDER BY source_id")


# ── 開關 ──────────────────────────────────────────────────────────────────────

def test_fetch_ships_off_by_default():
    assert ls.LODGING_FETCH_ENABLED is False


@pytest.mark.parametrize("val", [None, "0", "true", "yes", ""])
def test_switch_off_means_no_connection(net, monkeypatch, val):
    if val is None:
        monkeypatch.delenv(ls.FETCH_ENV, raising=False)
    else:
        monkeypatch.setenv(ls.FETCH_ENV, val)
    r = ls.refresh()
    assert r["ok"] is False and r["reason"] == "switch_off"
    assert net["calls"] == []


def test_demo_mode_never_connects(net, monkeypatch):
    monkeypatch.setattr(ls, "is_demo_mode", lambda: True)
    r = ls.refresh()
    assert r["reason"] == "demo" and net["calls"] == []


# ── 正常更新與不存個資欄位 ─────────────────────────────────────────────────────

def test_refresh_replaces_catalog_and_stores_no_personal_fields(net):
    r = ls.refresh()
    assert r["ok"] is True and r["count"] == 5, r
    assert len(net["calls"]) == 1
    cat = _catalog()
    assert len(cat) == 5
    assert cat[0]["dataset_updated_at"] == fx.DATASET_UPDATE
    assert cat[0]["record_updated_at"] == "2026-07-13T13:42:11+08:00"       # LG-S1：每筆登記時間
    assert cat[0]["address"] == "測試市測試區測試路1號"
    cols = set(cat[0])
    assert not cols & {"phone", "tel", "telephones", "operator", "tax_code", "organizations"}
    # 哨兵值不可以出現在任何一張旅宿表（D 審 Q2：電話、經營者、統編不存）
    for t in ("lodging_catalog", "lodging_searches", "lodging_search_items", "lodging_quotes"):
        for row in fx.rows("SELECT * FROM %s" % t):
            flat = " ".join(str(v) for v in row.values())
            for s in (fx.SENTINEL_PHONE, fx.SENTINEL_OPERATOR, fx.SENTINEL_TAXCODE):
                assert s not in flat, (t, s)
    st = ls.fetch_state()
    assert st["last_success_at"] == T0.isoformat(timespec="seconds") and st["count"] == 5


def test_second_refresh_replaces_not_appends(net):
    assert ls.refresh()["ok"]
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL
    net["blob"] = fx.good_zip([fx.hotel(9)], update="2026-09-29T14:30:00+08:00")
    assert ls.refresh()["ok"]
    cat = _catalog()
    assert [c["source_id"] for c in cat] == ["Hotel_TEST_000009"]


# ── 速率 ──────────────────────────────────────────────────────────────────────

def test_success_interval_blocks_without_connecting(net):
    assert ls.refresh()["ok"]
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL - timedelta(seconds=1)
    r = ls.refresh()
    assert r["reason"] == "rate_limited" and len(net["calls"]) == 1
    assert r["next_allowed_at"] == (T0 + ls.MIN_SUCCESS_INTERVAL).isoformat(timespec="seconds")
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL
    assert ls.refresh()["ok"] and len(net["calls"]) == 2          # 反向控制：到點就可以


def test_failure_keeps_old_catalog_and_cools_down(net):
    assert ls.refresh()["ok"]
    before = _catalog()
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL
    net["exc"] = OSError("timed out")
    r = ls.refresh()
    assert r["ok"] is False and r["reason"] == "fetch_failed" and "timed out" in r["message"]
    assert _catalog() == before                                   # 舊快照不動
    assert ls.fetch_state()["last_error"]
    net["exc"] = None
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL + ls.FAILURE_COOLDOWN - timedelta(seconds=1)
    assert ls.refresh()["reason"] == "rate_limited" and len(net["calls"]) == 2
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL + ls.FAILURE_COOLDOWN
    assert ls.refresh()["ok"] and len(net["calls"]) == 3


def test_concurrent_refresh_only_one_connects(net):
    assert ls._REFRESH_LOCK.acquire(blocking=False)
    try:
        r = ls.refresh()
    finally:
        ls._REFRESH_LOCK.release()
    assert r["reason"] == "busy" and net["calls"] == []


# ── zip 防護（LG-S3） ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["extra.txt", "../HotelList.json", "/etc/HotelList.json",
                                  "C:/HotelList.json", "sub\\HotelList.json", "a/../../x.json"])
def test_zip_rejects_unexpected_or_unsafe_names(net, name):
    assert ls.refresh()["ok"]
    before = _catalog()
    net["now"] = T0 + ls.MIN_SUCCESS_INTERVAL
    net["blob"] = fx.make_zip({"HotelList.json": fx.dataset([fx.hotel(9)]), name: b"x"})
    r = ls.refresh()
    assert r["reason"] == "fetch_failed", r
    assert _catalog() == before


def test_zip_whitelist_positive_control():
    files = ls.safe_unzip(fx.make_zip({n: b"{}" for n in ls.ZIP_ALLOWED_NAMES}))
    assert set(files) == set(ls.ZIP_ALLOWED_NAMES)


def test_zip_unzip_total_limit():
    blob = fx.make_zip({"HotelList.json": b"0" * 5000})
    with pytest.raises(ls.SourceError, match="上限"):
        ls.safe_unzip(blob, max_total=4999)
    assert ls.safe_unzip(blob, max_total=5000)                     # 反向控制：剛好等於上限可以


@pytest.mark.parametrize("blob,msg", [(b"not a zip", "不是有效的 zip"),
                                      (None, "沒有 HotelList.json")])
def test_zip_broken_or_missing_main_file(blob, msg):
    blob = blob if blob is not None else fx.make_zip({"manifest.csv": b"x"})
    with pytest.raises(ls.SourceError, match=msg):
        ls.safe_unzip(blob)


def test_download_size_limit(monkeypatch):
    class Resp:
        def __init__(self):
            self.left = 3

        def read(self, n):
            if self.left:
                self.left -= 1
                return b"x" * 10
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ls.urllib.request, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(ls, "MAX_DOWNLOAD_BYTES", 25)
    with pytest.raises(ls.SourceError, match="上限"):
        ls.fetch_raw()
    monkeypatch.setattr(ls, "MAX_DOWNLOAD_BYTES", 30)
    assert ls.fetch_raw() == b"x" * 30


def test_download_total_time_limit(monkeypatch):
    """D 稽核 E2-S1：對方慢慢送（每次讀取都在逾時內）也不可以一直握著更新鎖。"""
    class Resp:
        def read(self, n):
            return b"x"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    clock = {"t": 0.0}

    def tick():
        clock["t"] += 10.0
        return clock["t"]
    monkeypatch.setattr(ls.urllib.request, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(ls.time, "monotonic", tick)
    with pytest.raises(ls.SourceError, match="總時限"):
        ls.fetch_raw()
    assert clock["t"] <= ls.FETCH_TOTAL_SECONDS + 30          # 到點就停，不是讀完才停


# ── 解析：來源改版 ─────────────────────────────────────────────────────────────

def test_parse_rejects_shape_change():
    with pytest.raises(ls.SourceError, match="缺 Hotels"):
        ls.parse_dataset(b'{"UpdateTime": "2026-09-28T00:00:00", "Data": []}')
    with pytest.raises(ls.SourceError, match="UpdateTime"):
        ls.parse_dataset(fx.dataset([fx.hotel(1)], update="yesterday"))


def test_parse_rejects_when_too_few_recognised():
    good = [fx.hotel(i) for i in range(1, 10)]
    bad = [fx.hotel(100, PositionLat=None)]
    assert len(ls.parse_dataset(fx.dataset(good + bad))["rows"]) == 9      # 9/10＝90% ⇒ 收
    with pytest.raises(ls.SourceError, match="低於"):
        ls.parse_dataset(fx.dataset(good[:8] + bad + [fx.hotel(101, HotelClasses=[])]))   # 8/10


def test_parse_skips_out_of_taiwan_and_zero_prices():
    rows = ls.parse_dataset(fx.dataset(
        [fx.hotel(i) for i in range(1, 20)] + [fx.hotel(50, lat=35.0), fx.hotel(51, low=0, high=0)]))["rows"]
    ids = {r["source_id"]: r for r in rows}
    assert "Hotel_TEST_000050" not in ids
    assert ids["Hotel_TEST_000051"]["price_low"] is None and ids["Hotel_TEST_000051"]["price_high"] is None


# ── 端點 ──────────────────────────────────────────────────────────────────────

def test_status_without_catalog_is_not_zero_results(client, make_user):
    h = fx.token(client, make_user, "lod_user", "sales", modules=["lodging"])
    d = client.get("/api/lodging/status", headers=h).json()
    assert d["count"] == 0 and d["datasetUpdatedAt"] == "" and d["canRefresh"] is False
    assert d["fetchEnabled"] in (True, False) and d["attribution"] == ""


def test_status_after_refresh_has_attribution_with_dataset_year(client, make_user, net):
    assert ls.refresh()["ok"]
    h = fx.token(client, make_user, "lod_user2", "sales", modules=["lodging"])
    d = client.get("/api/lodging/status", headers=h).json()
    assert d["count"] == 5 and d["datasetUpdatedAt"] == fx.DATASET_UPDATE
    assert "交通部觀光署 2026 旅館民宿 - 觀光資訊資料庫" in d["attribution"]
    assert "https://data.gov.tw/license" in d["attribution"]


def test_module_permission_required(client, make_user):
    h = fx.token(client, make_user, "lod_none", "sales", modules=["dashboard"])
    assert client.get("/api/lodging/status", headers=h).status_code == 403


def test_only_superadmin_can_refresh(client, make_user, net):
    h = fx.token(client, make_user, "lod_admin", "admin", modules=["lodging"])
    assert client.post("/api/lodging/refresh", headers=h).status_code == 403
    assert net["calls"] == []
    s = fx.token(client, make_user, "lod_super", "superadmin")
    r = client.post("/api/lodging/refresh", headers=s)
    assert r.status_code == 200 and r.json()["ok"] is True and len(net["calls"]) == 1
