# -*- coding: utf-8 -*-
"""部署零行為變更的凍結基準（依擁有者分檔；脊柱 E-a）。

- 核心：`tests/platform/settings_deploy_baseline.json`（只含 owner＝core 的群組）。
- 模組：`modules/<模組>/tests/settings_deploy_baseline.json`（只含該模組擁有的群組）。
- 比對只針對**目前登錄表裡真的有群組的擁有者**：模組沒載入 ⇒ 它的基準不參與；
  核心比對用 owner 過濾，與『前面有沒有題載入過模組』無關（順序獨立）。
- 格式：`{"groups": {群組: {欄位: [預設, 下限, 上限, clamp]}}}`。
"""
import json
from pathlib import Path

from helpers import settings_groups  # noqa: F401  核心群組
from helpers import settings_registry as R

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
CORE_BASELINE = HERE / "settings_deploy_baseline.json"


def baseline_path(owner):
    return CORE_BASELINE if owner == "core" else BACKEND / "modules" / owner / "tests" / "settings_deploy_baseline.json"


def snapshot_of(owner):
    """登錄表裡 owner 的群組（排除測試用的 zz_ 群組）→ 基準格式。"""
    return {g: {f["key"]: [f["default"], f["min"], f["max"], f["clamp"]] for f in m["fields"]}
            for g, m in R.groups().items() if m["owner"] == owner and not g.startswith("zz_")}


def owners_with_groups():
    return sorted({m["owner"] for g, m in R.groups().items() if not g.startswith("zz_")})


def problems(owner):
    """owner 的登錄表與凍結基準的差異（空＝一致）。沒有群組也沒有基準檔 ⇒ 沒有要比的東西 ⇒ 空。"""
    now = snapshot_of(owner)
    path = baseline_path(owner)
    if not path.exists():
        return ["%s：登錄了群組 %s，但沒有凍結基準檔 %s" % (owner, sorted(now), path)] if now else []
    frozen = json.loads(path.read_text(encoding="utf-8")).get("groups", {})
    out = []
    for g in sorted(set(now) | set(frozen)):
        if g not in now:
            out.append("%s：基準有群組 %s，登錄表沒有（群組被移除或改名？）" % (owner, g))
        elif g not in frozen:
            out.append("%s：登錄表有群組 %s，基準沒有（新增群組要同步凍結基準）" % (owner, g))
        elif now[g] != frozen[g]:
            for k in sorted(set(now[g]) | set(frozen[g])):
                if now[g].get(k) != frozen[g].get(k):
                    out.append("%s：%s.%s 預設／範圍改變：基準 %r → 現在 %r（改預設＝行為變更，要同步基準並走裁示）" % (owner, g, k, frozen[g].get(k), now[g].get(k)))
    return out
