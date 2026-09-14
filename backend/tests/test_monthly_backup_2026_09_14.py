"""月備份（永久保留層）真的會被寫出來——2026-09-14 使用者裁示「長久只留月備份」。

這裡不測「_monthly_backup() 有沒有被呼叫」，測的是**跑完 _daily_backup() 之後
雲端存檔目錄裡到底多了什麼檔案**。理由：這一層的整個價值就是「N 年後還找得到
那個月的完整資料」，而它每個月只會真的執行一次、失敗了也沒有人會在當下發現——
只有內容層級的斷言擋得住。

每一題都吃 `isolated_archive` fixture（見 conftest）——存檔目錄在 `_app` 是
session 級共用的，不隔離的話上一題留下的 `.done` marker 會讓下一題的備份
直接早退，斷言驗到的是別題造成的狀態。
"""
import json
import os
from datetime import date


def _month_dir(archive_mod):
    return os.path.join(archive_mod._monthly_dir(), date.today().strftime("%Y-%m"))


def _daily_dir_today(archive_mod):
    return os.path.join(archive_mod._daily_dir(), date.today().isoformat())


def test_daily_backup_also_writes_monthly_layer(isolated_archive):
    import archive

    archive._daily_backup()

    md = _month_dir(archive)
    assert os.path.isdir(md), "跑完每日備份後應該要有當月的月備份資料夾"
    assert os.path.isfile(os.path.join(md, ".done")), "月備份完成應留下 .done marker"

    # 月備份的 JSON 檔清單必須跟每日備份完全一致——這是「共用同一段匯出邏輯」
    # 的重點：日後有人新增資料表，兩邊會一起有，不會只有其中一邊。
    def _jsons(d):
        return sorted(n for n in os.listdir(d) if n.endswith(".json") and n != "彙總.json")

    assert _jsons(md) == _jsons(_daily_dir_today(archive))
    assert len(_jsons(md)) >= 40, "JSON 層應涵蓋 40 張表以上（2026-09-14 起為 41 張）"


def test_monthly_layer_includes_full_db_not_only_json(isolated_archive):
    """JSON 那層刻意不收憑證欄位與內嵌影像（見 §8.3），只有整庫 .db 是完整的。
    長期保留的那一份如果只有 JSON，等於長期保留了一份殘缺的資料。"""
    import archive

    archive._daily_backup()

    db_copy = os.path.join(_month_dir(archive), "motrix_erp.db")
    assert os.path.isfile(db_copy), "月備份必須含整份 motrix_erp.db"
    assert os.path.getsize(db_copy) > 0

    summary = json.load(open(os.path.join(_month_dir(archive), "彙總.json"), encoding="utf-8"))
    assert summary["db_snapshot"] is True
    assert summary["month"] == date.today().strftime("%Y-%m")


def test_monthly_backup_is_idempotent_within_the_same_month(isolated_archive):
    """同一個月跑幾次每日備份，月備份只會真的寫一次——靠 .done marker。
    觀測點挑 audit_log 的 backup.monthly_ok 筆數（真正的下游效果），
    不是檔案的 mtime（那個在 Windows 上顆粒度不夠可靠）。"""
    import archive
    from db import get_db

    archive._daily_backup()
    # 第二次要真的重跑每日那一層，所以先把每日的 .done 拿掉；
    # 月備份自己的 marker 留著，驗證它擋得住。
    daily_marker = os.path.join(_daily_dir_today(archive), ".done")
    if os.path.exists(daily_marker):
        os.remove(daily_marker)
    archive._daily_backup()

    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) c FROM audit_log WHERE action='backup.monthly_ok'").fetchone()["c"]
    conn.close()
    assert n == 1, f"同月重複執行不應重複寫月備份，實際 backup.monthly_ok 有 {n} 筆"


def test_monthly_failure_does_not_mark_done(isolated_archive, monkeypatch):
    """月備份是永久保留層，內容不完整比每日層嚴重得多——有表匯出失敗時
    **不寫 .done**，讓隔天的每日備份再試一次，而不是把一份殘缺的當成完成。"""
    import archive
    from db import get_db

    real_tables = archive._daily_backup_tables

    def _broken_tables():
        t = dict(real_tables())
        t["刻意壞掉的表"] = "SELECT * FROM 這張表不存在"
        return t

    monkeypatch.setattr(archive, "_daily_backup_tables", _broken_tables)
    archive._daily_backup()

    md = _month_dir(archive)
    assert os.path.isdir(md), "失敗仍應留下已匯出的部分供檢查"
    assert not os.path.exists(os.path.join(md, ".done")), \
        "有表匯出失敗時不得標記完成，否則這個月永遠拿不到完整的長期備份"

    conn = get_db()
    rows = [r["action"] for r in conn.execute(
        "SELECT action FROM audit_log WHERE action LIKE 'backup.monthly%'").fetchall()]
    conn.close()
    assert "backup.monthly_partial" in rows
    assert "backup.monthly_ok" not in rows
