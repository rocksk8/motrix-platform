# -*- coding: utf-8 -*-
"""「備份與監控」專頁的 API（L1；2026-11-13，系統選單提案 v2 批次 4a）。**全部只有最高管理者能用。**

- `GET  /api/system/backup-monitor`                    一頁看完的狀態（最近各種備份、雲端鏡像、硬碟、心跳、告警、保留天數、告警門檻）
- `POST /api/system/backup-monitor/backup-now`         {confirm: true} 立即備份（背景；同時只能一個、兩次至少隔 30 分鐘）
- `PUT  /api/system/backup-monitor/heartbeat-url`      {pingUrl: str, reason?: str} 設定／更換心跳網址（網址不會被回傳；更換會寄信給所有最高管理者；換成另一個主機要原因、有其他最高管理者時要核准）
- `POST /api/system/backup-monitor/heartbeat-test`     {confirm: true} 對目前網址打一次卡（至少隔 60 秒）
- `POST /api/system/backup-monitor/heartbeat-disable`  {confirm: true, reason} 停用對外打卡（必填原因；有多位最高管理者時要另一位核准）
- `POST /api/system/backup-monitor/heartbeat-disable/{id}/approve|cancel`   核准申請（停用，或換成另一個監控主機）／撤回申請（只有提出申請的人，留稽核）

資料與規則都在 `helpers/backup_monitor.py`（不變式見該檔）；告警門檻在設定中心 `monitoring` 群組（放寬要第二人核准，不在這裡改）。
錯誤訊息一律白話、不含路徑與網址；危險動作沒有 `confirm: true` 一律 400（前端先跳確認再送）。
"""
import logging

from fastapi import APIRouter, Body, Header, HTTPException, Request

from helpers import _require_user, _audit, _tok
from helpers import backup_monitor as bm

router = APIRouter()
logger = logging.getLogger(__name__)


def _need_confirm(body: dict, what: str) -> None:
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise HTTPException(400, "請先確認要%s。" % what)


def _safe_audit(authorization, *args, **kwargs) -> None:
    """動作已經做了，稽核寫失敗不能讓使用者看到 500（以為沒做成功而重按）；只記 log。"""
    try:
        _audit(_tok(authorization), *args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("備份與監控：稽核寫入失敗（動作本身已完成）")


def _ip(request: Request) -> str:
    try:
        return (request.client.host if request and request.client else "") or ""
    except Exception:  # noqa: BLE001
        return ""


@router.get("/api/system/backup-monitor")
def get_backup_monitor(authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    out = bm.status()
    hb = out.get("heartbeat")
    if isinstance(hb, dict) and "error" not in hb:
        try:
            req = bm.pending_disable()
        except Exception:  # noqa: BLE001
            logger.warning("備份與監控：讀停用申請失敗", exc_info=True)
            req = None
        if req:
            req["mine"] = req.pop("requestedByUser") == user["username"]
        hb["disableRequest"] = req
    return out


@router.post("/api/system/backup-monitor/backup-now")
def post_backup_now(body: dict = Body(default=None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "立即做一次備份")
    try:
        res = bm.run_backup_now()
    except bm.BackupBusy:
        raise HTTPException(409, bm.MSG_BUSY)
    except bm.BackupLockProblem:
        raise HTTPException(503, bm.BackupLockProblem.MESSAGE)
    except bm.BackupRateLimited as exc:
        raise HTTPException(429, "剛做過一次備份，請 %d 分鐘後再試。" % max(1, -(-exc.wait_seconds // 60)))
    _safe_audit(authorization, "system.backup_now", "system", "backup", "手動立即備份")
    return {"ok": True, "started": res["started"], "message": "已開始備份，完成後這頁會更新。備份在背景進行，不影響大家使用。"}


@router.put("/api/system/backup-monitor/heartbeat-url")
def put_heartbeat_url(request: Request, body: dict = Body(default=None), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    if not isinstance(body, dict) or not isinstance(body.get("pingUrl", ""), str):
        raise HTTPException(400, "請貼上監控服務給你的網址。")
    try:
        res = bm.set_ping_url(body.get("pingUrl", ""), user, body.get("reason", ""), _ip(request))
    except (bm.InvalidPingUrl, bm.DisableError) as exc:
        raise HTTPException(422, str(exc))
    except OSError:
        raise HTTPException(500, "沒有存成功：這台電腦寫不進監控設定檔，請檢查資料夾權限與硬碟空間。")
    # 稽核只記主機名，不記完整網址（網址等同密碼）；換網址時一併記舊主機名（申請待核准的那一筆，ledger 自己已記稽核）
    if res["pending"]:
        return {"ok": True, "pingUrlSet": res["pingUrlSet"], "pingHost": res["pingHost"], "changed": False, "pending": True, "id": res["id"],
                "message": "換成另一個監控主機需要另一位最高管理者核准，已送出申請並寄信通知所有最高管理者。核准前仍使用原本的網址。"}
    if res["changed"]:
        _safe_audit(authorization, "system.heartbeat_url_set", "system", "heartbeat", res["pingHost"],
                    {"pingUrlSet": True, "host": res["pingHost"], "oldHost": res["oldHost"], "mailed": res["mailed"]})
        msg = "已儲存，並寄信通知所有最高管理者。心跳排程下一次執行（最多 5 分鐘內）就會用新的網址，不用重新啟動。"
        if not res["mailed"]:
            msg += "但通知信沒有寄出去（可能沒有設定收件人或郵件服務），請自己告知其他最高管理者。"
    else:
        msg = "這個網址和目前的一樣，沒有變更。"
    return {"ok": True, "pingUrlSet": res["pingUrlSet"], "pingHost": res["pingHost"], "changed": res["changed"], "pending": False, "message": msg}


@router.post("/api/system/backup-monitor/heartbeat-disable")
def post_heartbeat_disable(request: Request, body: dict = Body(default=None), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "停用對外打卡")
    reason = body.get("reason", "") if isinstance(body, dict) else ""
    if not isinstance(reason, str):
        raise HTTPException(400, "請寫下停用的原因。")
    try:
        res = bm.request_disable(user, reason, _ip(request))
    except bm.DisableError as exc:
        raise HTTPException(422, str(exc))
    except OSError:
        raise HTTPException(500, "沒有存成功：這台電腦寫不進監控設定檔，請檢查資料夾權限與硬碟空間。")
    if res["disabled"]:
        return {"ok": True, **res, "message": "已停用對外打卡：系統只會檢查本機服務，不會通知外部監控。已寄信通知所有最高管理者。"}
    return {"ok": True, **res, "message": "已送出停用申請，要另一位最高管理者核准後才會停用。已寄信通知所有最高管理者。"}


@router.post("/api/system/backup-monitor/heartbeat-disable/{change_id}/approve")
def post_heartbeat_disable_approve(change_id: int, request: Request, body: dict = Body(default=None), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "核准停用對外打卡")
    try:
        res = bm.approve_disable(change_id, user, _ip(request))
    except bm.DisableError as exc:
        raise HTTPException(422, str(exc))
    except OSError:
        raise HTTPException(500, "沒有核准成功：這台電腦寫不進監控設定檔，請檢查資料夾權限與硬碟空間，再按一次。")
    return {"ok": True, **res, "message": "已核准，對外打卡已停用。" if res["disabled"] else ("已核准，已換成新的監控網址。" if res["changed"] else "已記錄你的核准。")}


@router.post("/api/system/backup-monitor/heartbeat-disable/{change_id}/cancel")
def post_heartbeat_disable_cancel(change_id: int, body: dict = Body(default=None), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        bm.cancel_disable(change_id, user)
    except bm.DisableError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True, "message": "已撤回申請，目前的設定維持不變。"}


@router.post("/api/system/backup-monitor/heartbeat-test")
def post_heartbeat_test(body: dict = Body(default=None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "測試心跳（會對外部監控服務打一次卡）")
    try:
        res = bm.test_heartbeat()
    except bm.HeartbeatRateLimited as exc:
        raise HTTPException(429, "剛測試過，請 %d 秒後再試。" % max(1, int(exc.wait_seconds) + 1))
    _safe_audit(authorization, "system.heartbeat_test", "system", "heartbeat", "測試心跳", {"ok": res["ok"]})
    return res
