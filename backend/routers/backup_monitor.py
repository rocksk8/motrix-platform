# -*- coding: utf-8 -*-
"""「備份與監控」專頁的 API（L1；2026-11-13，系統選單提案 v2 批次 4a）。**全部只有最高管理者能用。**

- `GET  /api/system/backup-monitor`                    一頁看完的狀態（最近各種備份、雲端鏡像、硬碟、心跳、告警、保留天數、告警門檻）
- `POST /api/system/backup-monitor/backup-now`         {confirm: true} 立即備份（背景；同時只能一個、兩次至少隔 30 分鐘）
- `PUT  /api/system/backup-monitor/heartbeat-url`      {pingUrl: str} 設定心跳網址（空字串＝停用對外打卡；網址不會被回傳）
- `POST /api/system/backup-monitor/heartbeat-test`     {confirm: true} 對目前網址打一次卡（至少隔 60 秒）

資料與規則都在 `helpers/backup_monitor.py`（不變式見該檔）；告警門檻在設定中心 `monitoring` 群組（放寬要第二人核准，不在這裡改）。
錯誤訊息一律白話、不含路徑與網址；危險動作沒有 `confirm: true` 一律 400（前端先跳確認再送）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _require_user, _audit, _tok
from helpers import backup_monitor as bm

router = APIRouter()


def _need_confirm(body: dict, what: str) -> None:
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise HTTPException(400, "請先確認要%s。" % what)


@router.get("/api/system/backup-monitor")
def get_backup_monitor(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    return bm.status()


@router.post("/api/system/backup-monitor/backup-now")
def post_backup_now(body: dict = Body(default=None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "立即做一次備份")
    try:
        res = bm.run_backup_now()
    except bm.BackupBusy:
        raise HTTPException(409, "已經有一次備份正在進行，請等它做完。")
    except bm.BackupRateLimited as exc:
        raise HTTPException(429, "剛做過一次備份，請 %d 分鐘後再試。" % max(1, -(-exc.wait_seconds // 60)))
    _audit(_tok(authorization), "system.backup_now", "system", "backup", "手動立即備份")
    return {"ok": True, "started": res["started"], "message": "已開始備份，完成後這頁會更新。備份在背景進行，不影響大家使用。"}


@router.put("/api/system/backup-monitor/heartbeat-url")
def put_heartbeat_url(body: dict = Body(default=None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if not isinstance(body, dict) or not isinstance(body.get("pingUrl", ""), str):
        raise HTTPException(400, "請貼上監控服務給你的網址。")
    try:
        res = bm.set_ping_url(body.get("pingUrl", ""))
    except bm.InvalidPingUrl as exc:
        raise HTTPException(422, str(exc))
    except OSError:
        raise HTTPException(500, "沒有存成功：這台電腦寫不進監控設定檔，請檢查資料夾權限與硬碟空間。")
    # 稽核只記主機名，不記完整網址（網址等同密碼）
    _audit(_tok(authorization), "system.heartbeat_url_set", "system", "heartbeat", res["pingHost"] or "（停用對外打卡）",
           {"pingUrlSet": res["pingUrlSet"], "host": res["pingHost"]})
    return {"ok": True, **res, "message": "已儲存。心跳排程下一次執行（最多 5 分鐘內）就會用新的網址，不用重新啟動。" if res["pingUrlSet"]
            else "已停用對外打卡：系統只會檢查本機服務，不會通知外部監控。"}


@router.post("/api/system/backup-monitor/heartbeat-test")
def post_heartbeat_test(body: dict = Body(default=None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need_confirm(body, "測試心跳（會對外部監控服務打一次卡）")
    try:
        res = bm.test_heartbeat()
    except bm.HeartbeatRateLimited as exc:
        raise HTTPException(429, "剛測試過，請 %d 秒後再試。" % max(1, int(exc.wait_seconds) + 1))
    _audit(_tok(authorization), "system.heartbeat_test", "system", "heartbeat", "測試心跳", {"ok": res["ok"]})
    return res
