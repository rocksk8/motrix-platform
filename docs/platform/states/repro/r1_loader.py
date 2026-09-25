"""STATES-PLATFORM R1：載入器／路由衝突的實際行為。不 import main。
用法（repo 根目錄）：python docs/platform/states/repro/r1_loader.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
from core import loader, registry  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="motrix-pytest-A-repro-"))
pkg = tmp / "rpk"
pkg.mkdir()
(pkg / "__init__.py").write_text("", encoding="utf-8")

OKINIT = ("from fastapi import APIRouter\nfrom core.registry import ModuleSpec\n"
          "r = APIRouter()\n@r.get('/api/dup/x')\ndef x():\n    return {'who': %r}\n"
          "MODULE = ModuleSpec(key=%r, routers=[r])\n")
cases = {
    "m_badjson": ("{壞", None),
    "m_nocore": (json.dumps({"key": "m_nocore"}), OKINIT % ("m_nocore", "m_nocore")),
    "m_badcore": (json.dumps({"key": "m_badcore", "core": ">=2.0,<3.0"}), OKINIT % ("m_badcore", "m_badcore")),
    "m_badrange": (json.dumps({"key": "m_badrange", "core": "~1.0"}), OKINIT % ("m_badrange", "m_badrange")),
    "m_keymismatch": (json.dumps({"key": "other", "core": ">=1.0,<2.0"}), OKINIT % ("x", "other")),
    "m_importerr": (json.dumps({"key": "m_importerr", "core": ">=1.0,<2.0"}), "import no_such_package_zz\n"),
    "m_noinit": (json.dumps({"key": "m_noinit", "core": ">=1.0,<2.0"}), None),       # 沒有 __init__.py
    "m_nomodule": (json.dumps({"key": "m_nomodule", "core": ">=1.0,<2.0"}), "X = 1\n"),  # 沒有 MODULE
    "m_dup_a": (json.dumps({"key": "m_dup_a", "core": ">=1.0,<2.0"}), OKINIT % ("m_dup_a", "m_dup_a")),
    "m_dup_b": (json.dumps({"key": "m_dup_b", "core": ">=1.0,<2.0"}), OKINIT % ("m_dup_b", "m_dup_b")),
}
for name, (mj, init) in cases.items():
    d = pkg / name
    d.mkdir()
    (d / "module.json").write_text(mj, encoding="utf-8")
    if init is not None:
        (d / "__init__.py").write_text(init, encoding="utf-8")
# 有程式、沒有 module.json
(pkg / "m_nomanifest").mkdir()
(pkg / "m_nomanifest" / "__init__.py").write_text(OKINIT % ("m_nomanifest", "m_nomanifest"), encoding="utf-8")

sys.path.insert(0, str(tmp))
registry._reset()
loader.load_all(str(pkg), "rpk", disabled=frozenset({"no_such_key"}))
for st in registry.module_states():
    print("%-14s %-9s %s" % (st["key"], st["state"], st["reason"][:90]))
print("m_nomanifest 出現在狀態表？", any(s["key"] == "m_nomanifest" for s in registry.module_states()))

# 兩個模組宣告同一條路由：FastAPI 實際給誰
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
app = FastAPI()
for m in registry.loaded():
    for r in m.spec.routers:
        app.include_router(r)
print("GET /api/dup/x →", TestClient(app).get("/api/dup/x").json(),
      "；同路徑路由數 =", sum(1 for r in app.routes if getattr(r, "path", "") == "/api/dup/x"))

# 載入兩次（測試或誤呼叫）：狀態會不會重複／殘留
loader.load_all(str(pkg), "rpk")
print("第二次載入後 loaded 數 =", len(registry.loaded()), "（第一次為 %d）" % 2)
import shutil  # noqa: E402
shutil.rmtree(tmp)
