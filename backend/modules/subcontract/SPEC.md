# M04 外包工班 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

~~本模組沒有專屬編號。搬遷時查過 `docs/windows/STATE.md`：……照舊留在 STATE.md。~~
〔更正（1.0.3）：反向控制（刪掉本模組跑 test_spec_coverage）抓到 `EM12` 的題全在本模組、條件卻在 STATE.md ⇒ 模組不在時條件變成「沒有題」。`EM12` 移進本檔；其餘跨模組編號（AC2、T9、X-9b 等）在本模組外仍有題，照舊留在 STATE.md〕

### 來源：STATE.md〈EM 系列〉（2026-09-26 M04 搬遷自 docs/windows/STATE.md 移入，原文照搬）

| 編號 | 條件 |
|---|---|
| **EM12** | 🔴 **跨 fetch 的假保護**：同一支函式裡兩支以上 fetch，**而只有第一支被檢查**；☠️ `vendor-contractors` 的**銀行存摺影本**沒存進去而畫面說成功（落在個資那條線上）；🔑 `EM9` 的判準**抓不到**（那支函式「有」失敗分支）；⚠️ **不知道還有幾個** |

行為的依據是本模組的測試（`modules/subcontract/tests/`；稽核 D M04-S3）與串接點 IP-1／IP-14／IP-15／IP-17（`docs/platform/INTEGRATION-POINTS.md`）。

## 範圍

（2026-09-26 自 `docs/windows/SCOPE.md` 移入）

### THIS

```
EM(1): EM12
```
