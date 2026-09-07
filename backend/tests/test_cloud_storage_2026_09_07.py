"""可插拔雲端備份儲存後端測試（2026-09-07，架構地圖 §6.4）。

`cloud_storage.py` 提供 S3 相容物件儲存後端，作為既有 G: 磁碟機掛載模式（磁碟機
代號漂移已造成過真實備份靜默失效事故，見 archive.py 歷史）的替代方案。目前沒有
真實 S3/B2 憑證可測試（見 MOTRIX-ERP-QUICK.md §12 2026-09-07 條目），這裡用一個
最小的假 S3 client（FakeS3Client，只實作實際會呼叫到的 5 個方法）驗證：
①`cloud_storage.py` 本身每個函式的邏輯正確 ②`archive.py` 在 backend="s3" 時
確實透過 `_cloud_*()` 派送層呼叫到假 client，而不是本機檔案系統。
"""
import json
from datetime import datetime, timezone

import archive
import cloud_storage


class FakeS3Client:
    """記憶體版最小 S3 client，只實作 cloud_storage.py 實際用到的方法。"""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.bucket_reachable = True

    def head_bucket(self, Bucket):
        if not self.bucket_reachable:
            raise RuntimeError("bucket unreachable")

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = bytes(Body)

    def upload_file(self, Filename, Bucket, Key):
        with open(Filename, "rb") as f:
            self.objects[Key] = f.read()

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey")
        return {
            "ContentLength": len(self.objects[Key]),
            "LastModified": datetime.now(timezone.utc),
        }

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, ContinuationToken=None):
        keys = [k for k in self.objects if k.startswith(Prefix)]
        if Delimiter:
            prefixes, contents = set(), []
            for k in keys:
                rest = k[len(Prefix):]
                if Delimiter in rest:
                    prefixes.add(Prefix + rest.split(Delimiter)[0] + Delimiter)
                else:
                    contents.append({"Key": k})
            return {"CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)],
                    "Contents": contents, "IsTruncated": False}
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"], None)


def _install_fake_s3(monkeypatch, client, bucket="test-bucket", prefix="motrix-erp-backups/"):
    """比照 cloud_backup_target() 的形狀灌一份 s3 設定並接上假 client。"""
    from helpers import _set_setting
    _set_setting("cloud_backup_target", {
        "backend": "s3",
        "s3": {"bucket": bucket, "endpoint_url": "", "region": "us-east-1", "prefix": prefix},
    })
    monkeypatch.setattr(cloud_storage, "_get_s3_client", lambda: client)
    cloud_storage.reset_s3_available_cache()


# ── cloud_storage.py 本身 ────────────────────────────────────────────────────

def test_default_target_is_local_drive(client):
    assert cloud_storage.cloud_backup_target()["backend"] == "local_drive"


def test_s3_put_and_stat_roundtrip(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    cloud_storage.s3_put_bytes("即時備份/報價單/MQ-1.json", b'{"a":1}')
    assert fake.objects["motrix-erp-backups/即時備份/報價單/MQ-1.json"] == b'{"a":1}'
    size, mtime = cloud_storage.s3_stat("即時備份/報價單/MQ-1.json")
    assert size == len(b'{"a":1}')
    assert mtime > 0


def test_s3_stat_missing_returns_none(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    assert cloud_storage.s3_stat("does/not/exist.json") is None


def test_s3_available_true_when_bucket_reachable(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    assert cloud_storage.s3_available() is True


def test_s3_available_false_when_bucket_unreachable(client, monkeypatch):
    fake = FakeS3Client()
    fake.bucket_reachable = False
    _install_fake_s3(monkeypatch, fake)
    assert cloud_storage.s3_available() is False


def test_s3_available_false_when_no_bucket_configured(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake, bucket="")
    assert cloud_storage.s3_available() is False


def test_s3_list_prefixes_and_delete(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    cloud_storage.s3_put_bytes("每日備份/2026-01-01/彙總.json", b"{}")
    cloud_storage.s3_put_bytes("每日備份/2026-02-02/彙總.json", b"{}")
    names = cloud_storage.s3_list_prefixes("每日備份")
    assert sorted(names) == ["2026-01-01", "2026-02-02"]

    cloud_storage.s3_delete_prefix("每日備份/2026-01-01")
    names_after = cloud_storage.s3_list_prefixes("每日備份")
    assert names_after == ["2026-02-02"]
    assert "motrix-erp-backups/每日備份/2026-02-02/彙總.json" in fake.objects


# ── archive.py 派送層在 backend="s3" 時的整合行為 ────────────────────────────

def test_archive_ok_reflects_s3_backend(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    assert archive._archive_ok() is True
    fake.bucket_reachable = False
    cloud_storage.reset_s3_available_cache()
    assert archive._archive_ok() is False


def test_backup_quotation_writes_to_s3_not_local(client, monkeypatch, tmp_path):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    import db
    conn = db.get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("MQ-S3-001", "草稿", "客戶A", "專案A", 1000, 950, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    archive._backup_quotation("MQ-S3-001")

    key = "motrix-erp-backups/即時備份/報價單/MQ-S3-001.json"
    assert key in fake.objects
    payload = json.loads(fake.objects[key])
    assert payload["quote_no"] == "MQ-S3-001"
    # 本機即時備份 fallback 目錄不應該被寫入（雲端已經可用）
    local_fallback = archive._LOCAL_DB_BACKUP
    import os
    assert not os.path.exists(os.path.join(local_fallback, "quotation_instant", "MQ-S3-001.json"))


def test_mirror_uploads_to_s3(client, monkeypatch, tmp_path):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    uploads = tmp_path / "uploads"
    (uploads / "projects" / "1").mkdir(parents=True)
    (uploads / "projects" / "1" / "photo.jpg").write_bytes(b"fake-jpeg-bytes")
    monkeypatch.setattr(archive, "_UPLOADS_DIR", str(uploads))

    copied = archive._mirror_uploads()
    assert copied == 1
    key = "motrix-erp-backups/上傳檔案鏡像/projects/1/photo.jpg"
    assert fake.objects[key] == b"fake-jpeg-bytes"

    # 不變的檔案第二次不應該重新上傳（用 head_object 比對 size/mtime）
    copied_again = archive._mirror_uploads()
    assert copied_again == 0


def test_daily_backup_writes_to_s3_and_marker_prevents_rerun(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    monkeypatch.setattr(archive, "_UPLOADS_DIR", "___nonexistent___")

    archive._daily_backup()

    from datetime import date
    today = date.today().isoformat()
    assert f"motrix-erp-backups/每日備份/{today}/彙總.json" in fake.objects
    assert f"motrix-erp-backups/每日備份/{today}/.done" in fake.objects

    put_count_before = len(fake.objects)
    archive._daily_backup()  # marker 存在，應該直接 return，不重新產生
    assert len(fake.objects) == put_count_before


def test_prune_cloud_backups_deletes_expired_s3_prefix(client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    cloud_storage.s3_put_bytes("每日備份/2020-01-01/彙總.json", b"{}")
    cloud_storage.s3_put_bytes("每日備份/2020-01-01/報價單.json", b"{}")

    from datetime import date
    today = date.today().isoformat()
    cloud_storage.s3_put_bytes(f"每日備份/{today}/彙總.json", b"{}")

    archive._prune_cloud_backups(daily_keep_days=365, weekly_keep_days=730)

    remaining = cloud_storage.s3_list_prefixes("每日備份")
    assert "2020-01-01" not in remaining
    assert today in remaining


# ── GET/PUT /api/settings/cloud-backup-target ───────────────────────────────

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_requires_superadmin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/settings/cloud-backup-target", headers=_auth(token))
    assert r.status_code == 403, r.text


def test_get_default(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.get("/api/settings/cloud-backup-target", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["backend"] == "local_drive"


def test_put_requires_superadmin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.put("/api/settings/cloud-backup-target", headers=_auth(token),
                    json={"backend": "local_drive"})
    assert r.status_code == 403, r.text


def test_put_s3_requires_bucket(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.put("/api/settings/cloud-backup-target", headers=_auth(token),
                    json={"backend": "s3", "s3": {"bucket": ""}})
    assert r.status_code == 400, r.text


def test_put_rejects_unknown_backend(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.put("/api/settings/cloud-backup-target", headers=_auth(token),
                    json={"backend": "google_drive_api"})
    assert r.status_code == 400, r.text


def test_put_s3_persists_and_reflected_in_archive(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.put("/api/settings/cloud-backup-target", headers=_auth(token), json={
        "backend": "s3",
        "s3": {"bucket": "motrix-backups", "endpoint_url": "https://s3.us-west-002.backblazeb2.com",
               "region": "us-west-002", "prefix": "prod/"},
    })
    assert r.status_code == 200, r.text

    g = client.get("/api/settings/cloud-backup-target", headers=_auth(token))
    body = g.json()
    assert body["backend"] == "s3"
    assert body["s3"]["bucket"] == "motrix-backups"
    assert body["s3"]["endpoint_url"] == "https://s3.us-west-002.backblazeb2.com"
    assert archive._active_backend() == "s3"
