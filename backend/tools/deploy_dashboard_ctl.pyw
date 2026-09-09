"""部署儀表板開關小程式（2026-09-09 新增）——把原本的
deploy_dashboard_start.bat / deploy_dashboard_stop.bat 合併成單一視窗，
只有「開啟」跟「關閉」兩顆按鈕。

啟動方式：雙擊本檔（或桌面捷徑「MOTRIX 部署儀表板」，指向 pythonw.exe）。
本身不碰 WinRM、不碰正式機，只負責在本機把 deploy_dashboard.py
（127.0.0.1:8765）拉起來／停掉，見 MOTRIX-ERP-QUICK.md §14.3c。
"""
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
SERVER_SCRIPT = TOOLS_DIR / "deploy_dashboard.py"
RUN_LOG = TOOLS_DIR / "deploy_dashboard_run.log"

# 子行程一律不開主控台視窗；伺服器輸出全部導進 RUN_LOG。
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

BG = "#f4f5f7"
FG = "#1f2328"
MUTED = "#6b7280"
GREEN = "#1a7f37"
RED = "#b42318"
GREY = "#9ca3af"
DISABLED_BG = "#d3d6db"
AMBER_DOT = "#d29922"
AMBER_TEXT = "#9a6700"
UI_FONT = "Microsoft JhengHei UI"


def port_in_use() -> bool:
    """只做 TCP 連線測試——不依賴任何會被系統語系影響的指令輸出。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _powershell(script: str) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.stdout.decode("utf-8", "replace")


def listeners() -> list:
    """回傳 [(pid, 行程名), ...]。用 Get-NetTCPConnection -State Listen，不像
    netstat 的狀態字串那樣有被系統語系影響的疑慮
    （見 feedback_windows_locale_encoding_pitfall）。"""
    out = _powershell(
        f"Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | "
        "ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
        '"$($_.OwningProcess);$($p.ProcessName)" }'
    )
    found, seen = [], set()
    for line in out.splitlines():
        pid, _, name = line.strip().partition(";")
        if pid.isdigit() and pid not in seen:
            seen.add(pid)
            found.append((int(pid), name.strip()))
    return found


def log_tail(n: int = 15) -> str:
    try:
        lines = RUN_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(讀不到 deploy_dashboard_run.log)"
    return "\n".join(lines[-n:]) or "(log 是空的)"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.busy = False
        root.title("MOTRIX 部署儀表板")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.geometry("400x250")

        tk.Label(
            root, text="MOTRIX 部署儀表板", bg=BG, fg=FG,
            font=(UI_FONT, 15, "bold"),
        ).pack(pady=(20, 2))
        tk.Label(
            root, text="打包 → 推送 → 套用到正式機", bg=BG, fg=MUTED,
            font=(UI_FONT, 9),
        ).pack()

        status_row = tk.Frame(root, bg=BG)
        status_row.pack(pady=(16, 14))
        self.dot = tk.Canvas(status_row, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(0, 7))
        self.status = tk.Label(status_row, text="檢查中…", bg=BG, fg=MUTED, font=(UI_FONT, 11))
        self.status.pack(side="left")

        btn_row = tk.Frame(root, bg=BG)
        btn_row.pack()
        self.btn_start = tk.Button(
            btn_row, text="開　啟", width=11, height=2, bd=0, cursor="hand2",
            bg=GREEN, fg="white", activebackground="#166b2e", activeforeground="white",
            disabledforeground="#8e949c",
            font=(UI_FONT, 11, "bold"), command=self.on_start,
        )
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop = tk.Button(
            btn_row, text="關　閉", width=11, height=2, bd=0, cursor="hand2",
            bg=RED, fg="white", activebackground="#8f1c13", activeforeground="white",
            disabledforeground="#8e949c",
            font=(UI_FONT, 11, "bold"), command=self.on_stop,
        )
        self.btn_stop.pack(side="left", padx=6)

        self.hint = tk.Label(root, text=URL, bg=BG, fg=MUTED, font=(UI_FONT, 9))
        self.hint.pack(pady=(16, 0))

        self.refresh()

    # ── 狀態輪詢 ────────────────────────────────────────────────
    def refresh(self):
        if not self.busy:
            self.paint(port_in_use())
        self.root.after(1500, self.refresh)

    @staticmethod
    def _set_button(btn, enabled: bool, color: str):
        """Tk 的 disabled 按鈕仍會保留自訂 bg，只靠文字變灰看不出來——連底色
        一起換掉，狀態才一眼可辨。"""
        btn.config(
            state="normal" if enabled else "disabled",
            bg=color if enabled else DISABLED_BG,
        )

    def paint(self, running: bool):
        self.dot.itemconfig(self.dot_id, fill=GREEN if running else GREY)
        self.status.config(
            text="執行中" if running else "已停止",
            fg=GREEN if running else MUTED,
        )
        self._set_button(self.btn_start, not running, GREEN)
        self._set_button(self.btn_stop, running, RED)

    def working(self, text: str):
        self.busy = True
        self.dot.itemconfig(self.dot_id, fill=AMBER_DOT)
        self.status.config(text=text, fg=AMBER_TEXT)
        self._set_button(self.btn_start, False, GREEN)
        self._set_button(self.btn_stop, False, RED)

    def done(self, message: str = None, error: str = None):
        self.busy = False
        self.paint(port_in_use())
        if error:
            self.hint.config(text="失敗")
            messagebox.showerror("MOTRIX 部署儀表板", error, parent=self.root)
        elif message:
            self.hint.config(text=message)

    # ── 開啟 ────────────────────────────────────────────────────
    def on_start(self):
        if port_in_use():
            webbrowser.open(URL)
            return
        self.working("啟動中…")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        exe = sys.executable
        windowless = Path(exe).with_name("pythonw.exe")
        if windowless.exists():
            exe = str(windowless)
        try:
            with RUN_LOG.open("ab") as log:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                log.write(f"\n=== start {stamp} ===\n".encode("utf-8"))
                log.flush()
                proc = subprocess.Popen(
                    [exe, str(SERVER_SCRIPT)],
                    cwd=str(BACKEND_DIR),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW,
                )
        except OSError as exc:
            self._finish(error=f"啟動失敗：{exc}")
            return

        # 最多等 20 秒讓 uvicorn 起來；中途行程就死掉的話直接把 log 尾巴貼出來。
        deadline = time.time() + 20
        while time.time() < deadline:
            if port_in_use():
                webbrowser.open(URL)
                self._finish(message="已啟動，瀏覽器已開啟")
                return
            if proc.poll() is not None:
                break
            time.sleep(0.4)

        self._finish(
            error="部署儀表板沒有起來。\n\ndeploy_dashboard_run.log 最後幾行：\n\n" + log_tail()
        )

    # ── 關閉 ────────────────────────────────────────────────────
    def on_stop(self):
        if not messagebox.askyesno(
            "確認關閉",
            "要關閉部署儀表板嗎？\n\n若目前正有部署／回滾在跑，會被中斷。",
            parent=self.root,
        ):
            return
        self.working("關閉中…")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self):
        targets = listeners()
        if not targets:
            self._finish(message="本來就沒有在執行")
            return

        # 只殺 python 系列行程——8765 若被別的東西佔用，寧可不動手也不誤殺。
        strangers = [
            f"{name} (PID {pid})" for pid, name in targets
            if not name.lower().startswith("python")
        ]
        if strangers:
            self._finish(
                error="佔用 8765 的不是 python 行程，為避免誤殺沒有動作：\n\n"
                + "\n".join(strangers)
            )
            return

        for pid, _ in targets:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )

        deadline = time.time() + 5
        while time.time() < deadline and port_in_use():
            time.sleep(0.3)
        if port_in_use():
            self._finish(error="關不掉，8765 仍在監聽。")
        else:
            self._finish(message="已關閉")

    def _finish(self, message: str = None, error: str = None):
        """從工作執行緒回到 Tk 主執行緒更新畫面。"""
        self.root.after(0, lambda: self.done(message=message, error=error))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
