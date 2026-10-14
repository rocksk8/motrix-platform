# -*- coding: utf-8 -*-
"""S-ST2 階段樣板的兩條寫入類路由：先以有理由的豁免登記（金標案例需要同時開旗標＋建構器治理＋發布樣板，執行器的案例只有 setup(conn)，
表達不了『旗標開』這個前置；回應鍵集與狀態碼由 test_stage_apply_t63.py 守）。補成真案例時從這裡刪除並降低 WAIVE_CAP。"""

WAIVE = {
    "POST /api/quotations/stage-templates/preview":
        "preview：只在記憶體內驗證草稿樣板並以純函式算出會建立哪些階段，不寫任何資料；僅最高管理者、旗標 builder_stage_templates 關時 404（執行器的案例沒辦法開旗標）。"
        "狀態碼與回應鍵集由 tests/platform/test_stage_apply_t63.py（預覽、422 problems、旗標關 404）與 test_stage_templates_t62.py 守。",
    "POST /api/quotations/{quote_no}/stages/apply-template":
        "寫入 case_stages（並鏡像回 quotations.data_json），但前置條件是『旗標 builder_stage_templates＋建構器治理開啟且已發布樣板』，執行器的案例只有 setup(conn)，表達不了旗標與已發布樣板。"
        "回應鍵集（created／notes／stages…）、409 重複套用、404 旗標關、寫鎖與稽核 case_stage.apply_template 由 tests/platform/test_stage_apply_t63.py 守。",
}
