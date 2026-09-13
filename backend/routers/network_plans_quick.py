"""快速拓樸圖產生器：對應使用者原本個案腳本（B1F 拓樸圖產生器 b1f_topology.py）
的使用情境——只是想單純畫一張交換器埠位拓樸圖，不需要建立一份完整的網路架構
規劃書（不用填 WAN／VLAN／IP／防火牆…等其餘 9 個分頁）。

刻意設計成完全無狀態、不落地存檔：前端把 devices／switchPorts 資料整包放在
瀏覽器 localStorage（見 frontend/pages/topology-quick.html），這裡只負責把
收到的資料畫成 SVG 預覽或轉出 PDF，不寫進 network_plans 資料表，也不建立任何
規劃書紀錄——用完即丟，不需要走完整規劃書的建立/刪除/狀態流程。

路徑刻意用獨立的 /api/network-plans-quick 前綴（不是 /api/network-plans/xxx），
避免跟 network_plans.py 既有的 /api/network-plans/{plan_id} 參數化路由撞在一起。
"""
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import Response

from helpers import _require_user
from network_plan_export import build_topology_only_pdf_bytes
from network_plan_topology import build_topology_svg

router = APIRouter()

# 2026-09-13（模組權限稽核第二輪）：這支 router 的兩個端點**刻意不套模組檢查**。
# 它們是無狀態的繪圖工具（吃前端傳來的 JSON、回 SVG/PDF，不讀也不寫任何資料表），
# 擋它不會保護到任何資料，只會擋掉使用者畫圖。模組檢查的目的是資料可見性，
# 不是「凡是端點都要掛一道」。見 MODULE-AUDIT-2026-09-13.md §3.8 ④。


@router.post("/api/network-plans-quick/preview")
def preview_quick_topology(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    data = body.get("data") or {}
    try:
        result = build_topology_svg(data)
    except Exception as e:
        raise HTTPException(400, f"拓樸圖產生失敗：{e}")
    return {"svg": result.get("html"), "warnings": result.get("warnings") or []}


@router.post("/api/network-plans-quick/pdf")
def export_quick_topology_pdf(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    data = body.get("data") or {}
    title = (body.get("title") or "").strip()
    floor_tag = (body.get("floorTag") or "").strip()
    footer = (body.get("footer") or "").strip()
    try:
        pdf_bytes = build_topology_only_pdf_bytes(data, title, floor_tag, footer)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(500, str(e))
    filename = (title or "拓樸圖") + ".pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urlquote(filename)}"},
    )
