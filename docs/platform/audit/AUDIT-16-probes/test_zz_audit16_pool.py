r"""AUDIT-16 §5.1 附註：45 個同步慢處理函式占滿 threadpool 時，公開的 /api/ping 要等多久（基準與修正後都量過，各約 3.3 秒；不是授權閘門造成的）。
用法同 test_zz_audit16_probe.py（複製進 backend/tests、跑完刪掉）。輸出找 `POOL` 開頭的行。"""
import http.client
import threading
import time


def test_pool_starvation_public_ping(live_server, client, make_user):
    import main
    from fastapi import APIRouter
    r = APIRouter()

    @r.get("/api/_a16_slow")
    def _slow():                       # 同步處理函式 => 跑在 threadpool
        time.sleep(4.0)
        return {"ok": 1}
    main.app.router.routes.insert(0, r.routes[0])
    username, password = make_user(role="admin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    host, port = live_server.replace("http://", "").split(":")

    def call(path, h=None):
        t = time.perf_counter()
        c = http.client.HTTPConnection(host, int(port), timeout=60)
        c.request("GET", path, headers=h or {})
        rr = c.getresponse()
        rr.read()
        c.close()
        return rr.status, round(time.perf_counter() - t, 2)
    print("POOL ping alone:", call("/api/ping"))
    ts = [threading.Thread(target=call, args=("/api/_a16_slow", {"Authorization": "Bearer " + tok})) for _ in range(45)]
    for t in ts:
        t.start()
    time.sleep(1.0)
    print("POOL ping while 45 slow sync handlers hold the threadpool:", call("/api/ping"))
    for t in ts:
        t.join()
    main.app.router.routes.pop(0)
