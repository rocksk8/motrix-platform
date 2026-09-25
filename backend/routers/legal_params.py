# -*- coding: utf-8 -*-
"""法規參數（L1；ROADMAP 階段 R，規格 CUSTOMIZATION-SPEC §9）。

- GET  /api/legal-params/tax-rules          清單＋跨年狀態（superadmin）
- PUT  /api/legal-params/tax-rules          整份清單：結構驗證＋守門（門檻＝最低工資）＋已生效版本不可改刪（superadmin）
- GET  /api/legal-params/tax-basis-options  零稅率／免稅依據選項（登入即可）
- GET  /api/legal-params/privacy-notice     個資蒐集告知文字（登入即可；不含個資）
- GET  /api/legal-params/privacy-notice/texts/{hash}  已告知紀錄當時的告知全文（登入即可）
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _require_user, _tok, _audit
from helpers import legal_params as lp

router = APIRouter()


@router.get("/api/legal-params/tax-rules")
def get_tax_rule_versions(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    versions = lp.load_versions()
    return {"versions": versions, "status": lp.year_status(versions, lp.today())}


@router.get("/api/legal-params/tax-basis-options")
def get_tax_basis_options(authorization: str = Header(None)):
    """R2：零稅率／免稅依據的選項（報價頁、開票申請共用；唯一來源＝helpers.legal_params）。"""
    _require_user(authorization)
    return {
        "options": {k: [{"code": c, "label": lb, "noteRequired": c in lp.TAX_BASIS_NOTE_REQUIRED}
                        for c, lb in v] for k, v in lp.TAX_BASIS_OPTIONS.items()},
        # 稽核 S-4（2026-09-26）：§8 選項是逐字條文，出處給畫面顯示
        "sources": {"exempt": lp.ARTICLE_8_SOURCE},
    }


@router.get("/api/legal-params/privacy-notice")
def get_privacy_notice(authorization: str = Header(None)):
    """R3：列印告知書用的文字（登入即可讀；不含個資）。空白設定 ⇒ 範本。"""
    from helpers import privacy_notice as pn
    from helpers.settings import _get_setting
    _require_user(authorization)
    profile = _get_setting("company_profile", {}) or {}
    text = pn.notice_text(profile)
    return {"company": profile.get("name", ""), "text": text, "hash": pn.notice_hash(text),
            "isTemplate": not str(profile.get("privacy_notice") or "").strip(),
            "template": pn.template_for(profile.get("name", ""))}


@router.get("/api/legal-params/privacy-notice/texts/{notice_hash}")
def get_privacy_notice_text(notice_hash: str, authorization: str = Header(None)):
    """稽核 S-5：已告知紀錄上的 noticeHash ⇒ 當時告知的全文（紀錄寫入時存檔；只增不改）。"""
    from helpers import privacy_notice as pn
    _require_user(authorization)
    try:
        entry = pn.text_for_hash(notice_hash)
    except pn.AcksCorrupted as e:
        raise HTTPException(409, str(e))
    if entry is None:
        raise HTTPException(404, "查無這一版告知文字（本功能之前的紀錄沒有存全文）")
    return {"hash": notice_hash, "text": entry.get("text", ""), "firstAckAt": entry.get("firstAckAt")}


@router.put("/api/legal-params/tax-rules")
def put_tax_rule_versions(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    new = body.get("versions") if isinstance(body, dict) else None
    errs = lp.validate_versions(new)
    if not errs:
        errs = lp.frozen_changes(lp.load_versions(), new, lp.today())
    if errs:
        raise HTTPException(400, "；".join(errs))
    lp.save_versions(new)
    saved = lp.load_versions()
    _audit(_tok(authorization), "settings.tax_rules_versions.update", "settings", lp.VERSIONS_KEY,
           "法規參數", {"versions": [v["version"] + "@" + v["effectiveFrom"] for v in saved]})
    return {"versions": saved, "status": lp.year_status(saved, lp.today())}
