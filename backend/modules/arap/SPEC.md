# M05 應收應付 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。搬遷時查過：出納、開票申請、請款單的條件以跨模組編號記在 `docs/windows/STATE.md`（例：AS 系列簽核、JV 傳票來源、X-VAT 捨入），不是以本模組命名的編號；題大多在本模組外，照舊留在 STATE.md。反向控制（拿掉本模組跑 test_spec_coverage）若抓到題全在本模組的編號，再移進本檔（比照 M07 的 BN、M04 的 EM12）。

行為的依據是本模組的測試（`modules/arap/tests/`）與串接點（`docs/platform/INTEGRATION-POINTS.md`）。

## 刪除暫存區（第 53 班 P1，IP-RB1）
- 請款單、開票申請憑據的刪除端點進暫存區（可由最高管理者在 30 天內還原）；刪除條件不變（只准草稿）。暫存區模組不在時照舊硬刪，回應 `recycled:false` 並在稽核標籤明說。
- 還原不覆蓋：單號被占用、案件不存在 ⇒ 拒絕並留在暫存區。『刪除已核可』只收已核准；影響清單為資訊性（無收款／總帳／獎金下游）。
