"""Small window around the meeting-summary skill for people who never open a terminal.

Open it from the desktop shortcut, then pick a recording (or drop the file onto the shortcut).
It runs transcribe.py + frames.py locally, then asks Claude Code (`claude -p`, the user's own
login) to run the rest of SKILL.md, and finally lists the three HTML summaries to open in the browser.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "Scripts" / "python.exe"
PCT = re.compile(r"Transcribe .*?(\d+)%")
PROMPT = ("Use the meeting-summary skill on this recording: {path}\n"
          "Step 1 (transcript + slide frames) has already been run next to the file; continue from step 2. "
          "Nobody is available to answer questions, so run every remaining step to the end.")
CLAUDE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "PowerShell"]

# Monochrome palette: white page, light-grey cards, black hero; colour only in status badges.
BG, CARD, INK, MUTED, TRACK, DIM = "#FFFFFF", "#F4F4F5", "#0A0A0A", "#8A8A8F", "#DCDCE0", "#A1A1A6"
BADGES = {"idle": ("#EFEFF1", "#6B6B70", "รอไฟล์"), "run": ("#E8F0FE", "#3B7BEA", "กำลังทำงาน"),
          "ok": ("#E7F6EC", "#1E9E4A", "เสร็จแล้ว"), "fail": ("#FDECEC", "#D93A3A", "ไม่สำเร็จ")}
STEPS = ["ถอดเสียง", "เขียนสรุป", "สรุปพร้อม"]
OUTPUTS = [("_executive.html", "สรุปผู้บริหาร", "อ่านจบใน 3 นาที ตัวเลขสำคัญครบ"),
           ("_detailed.html", "รายงานฉบับเต็ม", "ทุกหัวข้อ พร้อมภาพสไลด์จากคลิป"),
           ("_plain.html", "ฉบับข้อความล้วน", "ไม่มีดีไซน์ ก๊อปไปวางใน Word หรืออีเมลได้ทันที")]
SCALE = 1.0  # screen DPI / 96, set once the Tk root exists


def px(n: float) -> int:
    return int(n * SCALE)


def font(size: int, weight: str = "normal"):
    return ("Leelawadee UI", size, weight)  # ships with Windows, covers Thai + Latin


def claude_exe() -> str:
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")


def auth_status() -> dict:
    """`claude auth status` as a dict ({} when Claude Code is missing or the call fails)."""
    try:
        out = subprocess.run([claude_exe(), "auth", "status"], capture_output=True, text=True, encoding="utf-8",
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        return json.loads(out)
    except Exception:
        return {}


def run(cmd, on_line, cwd=None) -> int:
    """Run without a console window, feeding each output line (\\r or \\n separated) to on_line."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    for line in p.stdout:
        if line.strip():
            on_line(line.rstrip())
    return p.wait()


def describe(event: dict):
    """stream-json event from `claude -p` -> short log line, or None."""
    if event.get("type") == "assistant":
        for c in event.get("message", {}).get("content", []):
            if c.get("type") == "tool_use":
                arg = c["input"].get("file_path") or c["input"].get("description") or ""
                return f"  • {c['name']} {Path(arg).name if c['input'].get('file_path') else arg}"
    if event.get("type") == "result":
        return event.get("result", "")
    return None


# --- drawn widgets (Tk has no rounded corners, so these paint on a Canvas) ---------------------
def rrect(c: tk.Canvas, x1, y1, x2, y2, r, fill, tags=""):
    """Filled rounded rectangle with true circular corners (r >= half the height gives a pill)."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    kw = dict(fill=fill, outline=fill, tags=tags)
    for x, y in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
        c.create_oval(x, y, x + 2 * r, y + 2 * r, **kw)
    c.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
    c.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)


class Card(tk.Frame):
    """Rounded panel that grows to fit its children; put them in .body.

    A plain Frame sizes itself from the body; the rounded shape is a Canvas placed behind it.
    """

    def __init__(self, parent, fill, radius=18, pad=18):
        super().__init__(parent, bg=parent["bg"])
        self.fill, self.r = fill, px(radius)
        self.bg = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, bd=0)
        self.bg.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg.bind("<Configure>", self._draw)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=px(pad), pady=px(pad))

    def _draw(self, e):
        self.bg.delete("all")
        rrect(self.bg, 0, 0, e.width - 1, e.height - 1, self.r, self.fill)


class Pill(tk.Canvas):
    """Fully rounded button; `dim` = (fill, ink) used while disabled."""

    def __init__(self, parent, text, command, fill, ink, dim, height=48, size=12):
        super().__init__(parent, bg=parent["bg"], height=px(height), highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command, self.colors, self.dim, self.size = text, command, (fill, ink), dim, size
        self.enabled = True
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        fill, ink = self.colors if self.enabled else self.dim
        rrect(self, 0, 0, w - 1, h - 1, h / 2, fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=ink, font=font(self.size, "bold"))


class Badge(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=px(30))
        self.f = tkfont.Font(font=font(9, "bold"))
        self.set("idle")

    def set(self, kind: str):
        fill, ink, text = BADGES[kind]
        w, h = self.f.measure(text) + px(28), px(30)
        self.configure(width=w)
        self.delete("all")
        rrect(self, 0, 0, w - 1, h - 1, h / 2, fill)
        self.create_text(w / 2, h / 2, text=text, fill=ink, font=self.f)


class Steps(tk.Canvas):
    """Three-node tracker: finished nodes are black with a check, the active one a ring."""

    def __init__(self, parent):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=px(70))
        self.done, self.frac, self.failed, self.times = 0, 0.0, False, ["", "", ""]
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, done=None, frac=None, failed=None):
        if done is not None and done != self.done or not any(self.times):
            stamp = time.strftime("%H:%M")
            for i in range(min(done or 0, 2) + 1):
                self.times[i] = self.times[i] or stamp
        self.done = self.done if done is None else done
        self.frac = self.frac if frac is None else frac
        self.failed = self.failed if failed is None else failed
        self.draw()

    def reset(self):
        self.done, self.frac, self.failed, self.times = 0, 0.0, False, ["", "", ""]
        self.draw()

    def draw(self):
        self.delete("all")
        w, r, y = self.winfo_width(), px(11), px(13)
        xs = [r + 1, w / 2, w - r - 1]
        self.create_line(xs[0], y, xs[2], y, fill=TRACK, width=px(4), capstyle="round")
        end = xs[2] if self.done >= 2 else xs[self.done] + (xs[self.done + 1] - xs[self.done]) * self.frac
        self.create_line(xs[0], y, end, y, fill=INK, width=px(4), capstyle="round")
        for i, x in enumerate(xs):
            if i < self.done:
                self.create_oval(x - r, y - r, x + r, y + r, fill=INK, outline=INK)
                self.create_line(x - px(5), y, x - px(1), y + px(4), x + px(5), y - px(4),
                                 fill="white", width=max(2, px(2)), capstyle="round", joinstyle="round")
            elif i == self.done and any(self.times):
                ring = "#D93A3A" if self.failed else INK
                self.create_oval(x - r, y - r, x + r, y + r, fill="white", outline=ring, width=px(3))
                self.create_oval(x - px(4), y - px(4), x + px(4), y + px(4), fill=ring, outline=ring)
            else:
                self.create_oval(x - r, y - r, x + r, y + r, fill=TRACK, outline=TRACK)
            anchor = ("w", "center", "e")[i]
            lx = x - r if i == 0 else x + r if i == 2 else x
            reached = i <= self.done and any(self.times)
            self.create_text(lx, y + r + px(14), text=STEPS[i], anchor=anchor, font=font(10, "bold" if reached else "normal"),
                             fill=INK if reached else MUTED)
            self.create_text(lx, y + r + px(31), text=self.times[i], anchor=anchor, font=font(8), fill=MUTED)


def link(parent, text, command) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=font(9), bg=parent["bg"], fg=MUTED, cursor="hand2")
    lbl.base = MUTED  # colour to return to after hover; callers may change it
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>", lambda e: lbl.configure(fg=INK))
    lbl.bind("<Leave>", lambda e: lbl.configure(fg=lbl.base))
    return lbl


class App:
    def __init__(self, root: tk.Tk):
        global SCALE
        SCALE = root.winfo_fpixels("1i") / 96
        self.root, self.q, self.files, self.creeping = root, queue.Queue(), [], False
        self.account, self.running = None, False  # account: None until the first status check returns
        root.title("สรุปประชุม")
        if (HERE / "icon.ico").exists():
            root.iconbitmap(default=str(HERE / "icon.ico"))
        root.configure(bg=BG)
        root.minsize(px(500), 0)
        root.resizable(False, False)
        page = tk.Frame(root, bg=BG)
        page.pack(fill="both", expand=True, padx=px(24), pady=(px(16), px(14)))

        head = tk.Frame(page, bg=BG)
        head.pack(fill="x", pady=(0, px(10)))
        tk.Label(head, text="สรุปประชุม", font=font(18, "bold"), bg=BG, fg=INK).pack(side="left")
        acct = tk.Frame(head, bg=BG)
        acct.pack(side="right")
        self.who = tk.Label(acct, text="กำลังตรวจสอบบัญชี Claude…", font=font(9), bg=BG, fg=MUTED)
        self.who.pack(anchor="e")
        self.auth_link = link(acct, "", self.auth_action)
        self.auth_link.pack(anchor="e")

        hero = Card(page, INK, radius=24, pad=22)
        hero.pack(fill="x")
        h = hero.body
        tk.Label(h, text="ไฟล์ประชุม · ได้สรุป 3 ฉบับเปิดในเบราว์เซอร์", font=font(9), bg=INK, fg=DIM).pack(anchor="w")
        self.file = tk.Label(h, text="ยังไม่ได้เลือกไฟล์", font=font(15, "bold"), bg=INK, fg="white",
                             anchor="w", justify="left")
        self.file.pack(fill="x", pady=(px(2), px(2)))
        h.bind("<Configure>", lambda e: self.file.configure(wraplength=e.width), add="+")
        self.hint = tk.Label(h, text="วิดีโอหรือเสียง · คลิปยาวอาจใช้เวลาเป็นชั่วโมง", font=font(9), bg=INK, fg=DIM)
        self.hint.pack(anchor="w")
        self.btn = Pill(h, "เลือกไฟล์ประชุม", self.pick, fill="white", ink=INK, dim=("#2C2C2E", "#6B6B70"))
        self.btn.pack(fill="x", pady=(px(18), 0))

        prog = Card(page, CARD, radius=20, pad=20)
        prog.pack(fill="x", pady=(px(12), 0))
        p = prog.body
        top = tk.Frame(p, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="ความคืบหน้า", font=font(12, "bold"), bg=CARD, fg=INK).pack(side="left")
        self.badge = Badge(top)
        self.badge.pack(side="right")
        self.steps = Steps(p)
        self.steps.pack(fill="x", pady=(px(16), px(4)))
        self.status = tk.Label(p, text="เลือกไฟล์เพื่อเริ่ม", font=font(10), bg=CARD, fg=MUTED,
                               anchor="w", justify="left")
        self.status.pack(fill="x")
        p.bind("<Configure>", lambda e: self.status.configure(wraplength=e.width), add="+")

        self.results = Card(page, CARD, radius=20, pad=5)  # filled with one row per summary when done
        self.foot = tk.Frame(page, bg=BG)
        self.foot.pack(fill="x", pady=(px(12), 0))
        self.toggle = link(self.foot, "ดูรายละเอียด ▾", self.toggle_log)
        self.toggle.pack(side="left")
        self.reveal = link(self.foot, "แสดงในโฟลเดอร์", lambda: subprocess.run(["explorer", f"/select,{self.files[0]}"]))

        self.logcard = Card(page, CARD, radius=16, pad=14)
        self.log = tk.Text(self.logcard.body, width=1, height=8, font=("Consolas", 9), bg=CARD, fg="#4A4A4F",
                           relief="flat", bd=0, highlightthickness=0, state="disabled", wrap="word")
        self.log.pack(fill="both")
        root.after(100, self.pump)
        self.refresh_auth()

    # --- UI-thread side ---------------------------------------------------------------------
    # --- Claude account (login is stored in the user profile, so it survives restarts) -------
    def refresh_auth(self):
        threading.Thread(target=lambda: self.q.put(("auth", auth_status())), daemon=True).start()

    def logged_in(self) -> bool:
        return bool(self.account and self.account.get("loggedIn"))

    def auth_action(self):
        if self.running or self.account is None:
            return
        if self.logged_in():
            if not messagebox.askyesno("ออกจากระบบ Claude",
                                       "ออกจากระบบ Claude บนเครื่องนี้?\nครั้งถัดไปต้องเข้าสู่ระบบใหม่ก่อนสรุปประชุม"):
                return
            cmd, flags, wait = [claude_exe(), "auth", "logout"], subprocess.CREATE_NO_WINDOW, "กำลังออกจากระบบ…"
        else:  # own console window: if the browser hand-off fails, Claude asks to paste a code there
            cmd, flags, wait = [claude_exe(), "auth", "login"], subprocess.CREATE_NEW_CONSOLE, "เข้าสู่ระบบในเบราว์เซอร์ที่เปิดขึ้นมา…"
        self.account = None
        self.who.configure(text=wait, fg=MUTED)
        self.auth_link.configure(text="")

        def go():
            try:
                subprocess.run(cmd, creationflags=flags, timeout=900)
            except Exception as e:
                self.q.put(("log", f"claude auth: {e!r}"))
            self.q.put(("auth", auth_status()))
        threading.Thread(target=go, daemon=True).start()

    def show_auth(self, status: dict):
        self.account = status
        if self.logged_in():
            email = status.get("email") or "Claude"
            self.who.configure(text="● " + (email if len(email) <= 28 else email[:26] + "…"), fg="#1E9E4A")
            self.auth_link.base = MUTED
            self.auth_link.configure(text="ออกจากระบบ", fg=MUTED, font=font(9))
        else:
            self.who.configure(text="ยังไม่ได้เข้าสู่ระบบ Claude", fg="#D93A3A")
            self.auth_link.base = INK
            self.auth_link.configure(text="เข้าสู่ระบบ →", fg=INK, font=font(10, "bold"))

    def toggle_log(self):
        if self.logcard.winfo_ismapped():
            self.logcard.pack_forget()
            self.toggle.configure(text="ดูรายละเอียด ▾")
        else:
            self.logcard.pack(fill="x", pady=(px(10), 0))
            self.toggle.configure(text="ซ่อนรายละเอียด ▴")

    def show_results(self, files):
        for w in self.results.body.winfo_children():
            w.destroy()
        for i, (path, title, desc) in enumerate(files):
            row = tk.Frame(self.results.body, bg=CARD, cursor="hand2")
            row.pack(fill="x", padx=px(12), pady=px(7))
            if i:
                tk.Frame(self.results.body, bg=TRACK, height=1).pack(fill="x", padx=px(12), before=row)
            go = Pill(row, "→", lambda p=path: os.startfile(p), fill=INK, ink="white", dim=(INK, "white"), height=34, size=11)
            go.configure(width=px(34))
            go.pack(side="right")
            text = tk.Frame(row, bg=CARD)
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=title, font=font(11, "bold"), bg=CARD, fg=INK, anchor="w").pack(fill="x")
            tk.Label(text, text=desc, font=font(9), bg=CARD, fg=MUTED, anchor="w").pack(fill="x")
            for w in (row, text, *text.winfo_children()):  # whole row is the click target
                w.bind("<Button-1>", lambda e, p=path: os.startfile(p))  # opens in the default browser
        self.results.pack(fill="x", pady=(px(12), 0), before=self.foot)

    def pump(self):
        while not self.q.empty():
            kind, val = self.q.get()
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", val + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "status":
                self.status.configure(text=val, fg=MUTED)
            elif kind == "step":
                self.steps.set(*val)
            elif kind == "auth":
                self.show_auth(val)
            elif kind == "creep":
                self.creeping = val
            elif kind == "end":
                ok, msg, files = val
                self.creeping = self.running = False
                self.btn.set_enabled(True)
                self.badge.set("ok" if ok else "fail")
                self.status.configure(text=msg, fg=INK if ok else "#D93A3A")
                if ok:
                    self.files = [f for f, _, _ in files]
                    self.steps.set(3, 0)
                    self.status.pack_forget()
                    self.show_results(files)
                    self.reveal.pack(side="right")
                else:
                    self.steps.set(failed=True)
                    self.refresh_auth()  # a failed run is often an expired login
        if self.creeping:  # Claude gives no %; ease the bar toward 90% so it never looks stuck
            self.steps.set(frac=self.steps.frac + (0.9 - self.steps.frac) * 0.0004)
        self.root.after(100, self.pump)

    def pick(self):
        if self.account is not None and not self.logged_in():
            return self.auth_action()  # log in first instead of failing 20 minutes later
        f = filedialog.askopenfilename(title="เลือกไฟล์ประชุม", filetypes=[
            ("คลิปประชุม", "*.mp4 *.mov *.mkv *.webm *.mp3 *.m4a *.wav"), ("ทุกไฟล์", "*.*")])
        if f:
            self.start(Path(f))

    def start(self, media: Path):
        self.running = True
        self.btn.set_enabled(False)
        self.results.pack_forget()
        self.status.pack(fill="x")
        self.reveal.pack_forget()
        self.file.configure(text=media.name)
        self.hint.pack_forget()  # keep the window short enough for a 1080p laptop at 150%
        self.badge.set("run")
        self.steps.reset()
        self.steps.set(0, 0)
        threading.Thread(target=self.work, args=(media,), daemon=True).start()

    # --- worker-thread side -----------------------------------------------------------------
    def work(self, media: Path):
        say = lambda kind, val=None: self.q.put((kind, val))
        try:
            say("log", f"ไฟล์: {media}")
            say("status", "กำลังถอดเสียงและเก็บภาพสไลด์ในเครื่องนี้…")

            def on_transcribe(line):
                say("log", line)
                m = PCT.search(line)
                if m:
                    say("step", (0, int(m.group(1)) / 100))

            frames = threading.Thread(target=run, args=([str(PY), str(HERE / "frames.py"), str(media)],
                                                        lambda l: say("log", l)))
            frames.start()
            code = run([str(PY), str(HERE / "transcribe.py"), str(media)], on_transcribe)
            frames.join()
            if code:
                return say("end", (False, "ถอดเสียงไม่สำเร็จ กด “ดูรายละเอียด” เพื่อดูสาเหตุ", None))

            say("step", (1, 0))
            say("creep", True)
            say("status", "Claude กำลังเขียนสรุปและอีเมล ประมาณ 5–15 นาที")
            result = {}

            def on_claude(line):
                try:
                    ev = json.loads(line)
                except ValueError:
                    return say("log", line)
                if ev.get("type") == "result":
                    result.update(ev)
                text = describe(ev)
                if text:
                    say("log", text)

            run([claude_exe(), "-p", PROMPT.format(path=media), "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "acceptEdits", "--allowedTools", *CLAUDE_TOOLS],
                on_claude, cwd=str(media.parent))
            files = [(media.with_name(media.stem + suffix), title, desc) for suffix, title, desc in OUTPUTS]
            files = [f for f in files if f[0].exists()]
            if result.get("is_error") or not files:
                return say("end", (False, "Claude ทำงานไม่สำเร็จ ตรวจว่ามุมขวาบนเข้าสู่ระบบอยู่ แล้วลองใหม่อีกครั้ง", None))
            say("end", (True, "กดเลือกฉบับที่ต้องการ จะเปิดในเบราว์เซอร์", files))
        except Exception as e:  # show anything unexpected instead of dying silently (pythonw has no console)
            say("log", repr(e))
            say("end", (False, f"เกิดข้อผิดพลาด: {e}", None))


if __name__ == "__main__":
    try:  # crisp text on scaled (125%/150%) laptop screens instead of bitmap-stretched blur
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("meeting-summary")  # taskbar shows our icon, not Python's
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():  # file dropped onto the desktop shortcut
        root.after(300, app.start, Path(sys.argv[1]))
    root.mainloop()
