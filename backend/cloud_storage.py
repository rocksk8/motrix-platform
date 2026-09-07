"""Pluggable cloud backup storage backend (2026-09-07, architecture map §6.4).

Two backends, selected by `system_settings.cloud_backup_target.backend`:

- **"local_drive"** (default, unchanged behavior): today's mapped
  cloud-sync drive letter (Google Drive for Desktop etc.), see
  `archive.py::_archive_base()`. This has a known weakness — the drive
  letter can silently drift (see `archive.py` history) — which is exactly
  what the "s3" backend below is meant to let a site move away from.
- **"s3"**: any S3-compatible object store (AWS S3, Backblaze B2's
  S3-compatible endpoint, MinIO, ...) via `boto3`. Bucket/endpoint/region/
  prefix live in `system_settings.cloud_backup_target.s3`; credentials are
  **never** stored there — `boto3`'s normal credential chain (environment
  variables / `~/.aws/credentials` / instance profile) is used instead, so
  nothing secret ends up sitting in the SQLite DB.

Setting up the "s3" backend on a real site:
  1. Create a bucket with the chosen provider (AWS S3, or Backblaze B2 —
     B2 exposes an S3-compatible endpoint, see architecture map §6.4 for
     why B2 is a reasonable low-cost pick for a company this size).
  2. Set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (B2's application
     key id/key work the same way) as environment variables on whichever
     machine runs the ERP service.
  3. `PUT /api/settings/cloud-backup-target` with
     `{"backend": "s3", "s3": {"bucket": "...", "endpoint_url": "...",
     "region": "...", "prefix": "motrix-erp-backups/"}}` (superadmin only).

This module was written and unit-tested against a fake in-memory S3 client
(see `tests/test_cloud_storage_2026_09_07.py`) — nobody had real S3/B2
credentials to verify a live bucket at the time this was written (see
`MOTRIX-ERP-QUICK.md` §12 2026-09-07 entry). Switching `backend` to "s3"
without a reachable bucket just makes `s3_available()` return False, which
`archive.py::_archive_ok()` treats exactly like an unmounted drive today
(same `_write_backup_alert()` path, no special-casing needed there).
"""
import logging
import threading
import time
from typing import Optional

from helpers import _get_setting

logger = logging.getLogger(__name__)

_CLOUD_TARGET_DEFAULT = {
    "backend": "local_drive",  # "local_drive" | "s3"
    "s3": {"bucket": "", "endpoint_url": "", "region": "us-east-1", "prefix": "motrix-erp-backups/"},
}


def cloud_backup_target() -> dict:
    stored = _get_setting("cloud_backup_target", {}) or {}
    merged = {**_CLOUD_TARGET_DEFAULT, **stored}
    merged["s3"] = {**_CLOUD_TARGET_DEFAULT["s3"], **(stored.get("s3") or {})}
    return merged


_client_lock = threading.Lock()
_client_cache = {"client": None, "config_key": None}


def _get_s3_client():
    """Lazily build (and cache) a boto3 S3 client for the currently configured
    endpoint/region; rebuilds if that config changes. Returns None if boto3
    isn't importable or client construction fails for any reason — callers
    treat that exactly like "cloud unavailable", same as an unmounted drive."""
    cfg = cloud_backup_target()["s3"]
    key = (cfg.get("endpoint_url"), cfg.get("region"))
    with _client_lock:
        if _client_cache["client"] is not None and _client_cache["config_key"] == key:
            return _client_cache["client"]
        try:
            import boto3
            client = boto3.client(
                "s3",
                region_name=cfg.get("region") or "us-east-1",
                endpoint_url=cfg.get("endpoint_url") or None,
            )
        except Exception:
            logger.exception("_get_s3_client: failed to build boto3 client")
            return None
        _client_cache["client"] = client
        _client_cache["config_key"] = key
        return client


def reset_s3_client_cache() -> None:
    """Force the next _get_s3_client() call to rebuild — used after changing
    the s3 settings via the API, and by tests that swap in a fake client."""
    with _client_lock:
        _client_cache["client"] = None
        _client_cache["config_key"] = None


_available_cache = {"ok": None, "checked_at": 0.0}
_AVAILABLE_TTL = 30  # seconds; mirrors archive.py's drive-mount cache pattern


def s3_available() -> bool:
    """head_bucket() is cheap but still a network round-trip — cache it for a
    short window so every single real-time backup write doesn't re-probe."""
    cached = _available_cache
    if cached["ok"] is not None and time.monotonic() - cached["checked_at"] < _AVAILABLE_TTL:
        return cached["ok"]
    ok = False
    cfg = cloud_backup_target()["s3"]
    bucket = cfg.get("bucket")
    client = _get_s3_client()
    if client is not None and bucket:
        try:
            client.head_bucket(Bucket=bucket)
            ok = True
        except Exception:
            logger.warning("s3_available: head_bucket failed for bucket=%r", bucket, exc_info=True)
    _available_cache["ok"] = ok
    _available_cache["checked_at"] = time.monotonic()
    return ok


def reset_s3_available_cache() -> None:
    _available_cache["ok"] = None
    _available_cache["checked_at"] = 0.0


def _s3_key(rel_path: str) -> str:
    prefix = cloud_backup_target()["s3"].get("prefix", "")
    rel = rel_path.replace("\\", "/").lstrip("/")
    return f"{prefix.rstrip('/')}/{rel}" if prefix else rel


def s3_put_bytes(rel_path: str, data: bytes) -> None:
    cfg = cloud_backup_target()["s3"]
    client = _get_s3_client()
    client.put_object(Bucket=cfg["bucket"], Key=_s3_key(rel_path), Body=data)


def s3_upload_file(local_path: str, rel_path: str) -> None:
    cfg = cloud_backup_target()["s3"]
    client = _get_s3_client()
    client.upload_file(local_path, cfg["bucket"], _s3_key(rel_path))


def s3_stat(rel_path: str) -> Optional[tuple]:
    """Returns (size, mtime_epoch_seconds) for an existing object, or None
    if it doesn't exist — the S3 equivalent of `os.stat()` used by
    `archive.py::_mirror_uploads()`'s "already copied, unchanged" check and
    by the daily/weekly `.done` marker check."""
    cfg = cloud_backup_target()["s3"]
    client = _get_s3_client()
    try:
        resp = client.head_object(Bucket=cfg["bucket"], Key=_s3_key(rel_path))
        return resp["ContentLength"], resp["LastModified"].timestamp()
    except Exception:
        return None


def s3_list_prefixes(rel_dir: str) -> list:
    """Top-level 'folder' names directly under rel_dir — the S3 equivalent of
    `os.listdir()` on a directory of subdirectories, used by
    `archive.py::_prune_cloud_backups()` to enumerate dated folders
    (YYYY-MM-DD / YYYY-Wxx) to evaluate for deletion."""
    cfg = cloud_backup_target()["s3"]
    client = _get_s3_client()
    full_prefix = _s3_key(rel_dir).rstrip("/") + "/"
    names = []
    token = None
    while True:
        kwargs = {"Bucket": cfg["bucket"], "Prefix": full_prefix, "Delimiter": "/"}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for cp in resp.get("CommonPrefixes", []) or []:
            name = cp["Prefix"][len(full_prefix):].rstrip("/")
            if name:
                names.append(name)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return names


def s3_delete_prefix(rel_dir: str) -> None:
    """Delete every object under rel_dir/ — the S3 equivalent of
    `shutil.rmtree()`, used to prune an expired dated backup folder."""
    cfg = cloud_backup_target()["s3"]
    client = _get_s3_client()
    full_prefix = _s3_key(rel_dir).rstrip("/") + "/"
    token = None
    while True:
        kwargs = {"Bucket": cfg["bucket"], "Prefix": full_prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        keys = [{"Key": o["Key"]} for o in resp.get("Contents", []) or []]
        if keys:
            client.delete_objects(Bucket=cfg["bucket"], Delete={"Objects": keys})
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
