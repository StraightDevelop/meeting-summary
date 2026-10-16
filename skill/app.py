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

APP_VERSION = "1.3.0"  # bump with every release and add a line under "เวอร์ชัน" in README.md
HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "Scripts" / "python.exe"
SPEED = HERE / "speed.json"  # this machine's measured transcription speed + Claude minutes, for the estimate
# transcribe.py progress: "[2/4] Detect language ..." and "[4/4] Transcribe ███░ 58%  01:45:12 / 03:01:07  elapsed .. ETA ~00:08:01"
STEP = re.compile(r"^\[\d/\d\] (Extract audio|Detect language|Load model|Transcribe) \.\.\.$")
PCT = re.compile(r"Transcribe .*?(\d+)%\s+(\S+) / (\S+) .*ETA ~(\S+)")
# step timings -> pure transcription speed (model load excluded: estimate() adds that per file)
AUDIO_LEN = re.compile(r"^\[1/4\] Extract audio \.\.\. done \(\S+\)\s+(\d+):(\d+):(\d+) of audio")
TRANSCRIBED = re.compile(r"^\[4/4\] Transcribe \.\.\. done \((\d+):(\d+):(\d+)\)")
STEP_TH = {"Extract audio": "กำลังแยกเสียงจากคลิป…", "Detect language": "กำลังตรวจว่าประชุมพูดภาษาอะไร…",
           "Load model": "กำลังโหลดโมเดลถอดเสียง…", "Transcribe": "เริ่มถอดเสียง…"}
# The app lists the summaries itself; opening them from Claude adds stray browser tabs, and on a PC with no
# .eml handler Windows shows "Pick an app", which minimized the app window in testing.
NO_OPEN = "Do not open any output file (no Start-Process / Invoke-Item on .html or .eml); this app lists them for the user."
PROMPT = ("Use the meeting-summary skill on this recording: {path}\n"
          "Step 1 (transcript + slide frames) has already been run next to the file; continue from step 2. "
          "Nobody is available to answer questions, so run every remaining step to the end. " + NO_OPEN)
PROMPT_PARTS = ("Use the meeting-summary skill on this meeting, recorded as {n} files in this order:\n{paths}\n"
                "It is ONE meeting: follow the multi-part section of SKILL.md, output stem `{stem}`. "
                "Step 1 (transcript + slide frames) has already been run next to each file; continue from step 2. "
                "Nobody is available to answer questions, so run every remaining step to the end. " + NO_OPEN)
CLAUDE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "PowerShell"]

# Monochrome palette: white page, light-grey cards, black hero; colour only in status badges.
BG, CARD, INK, MUTED, TRACK, DIM = "#FFFFFF", "#F4F4F5", "#0A0A0A", "#8A8A8F", "#DCDCE0", "#A1A1A6"
BADGES = {"idle": ("#EFEFF1", "#6B6B70", "รอไฟล์"), "ready": ("#EFEFF1", INK, "พร้อมเริ่ม"), "run": ("#E8F0FE", "#3B7BEA", "กำลังทำงาน"),
          "ok": ("#E7F6EC", "#1E9E4A", "เสร็จแล้ว"), "fail": ("#FDECEC", "#D93A3A", "ไม่สำเร็จ")}
STEPS = ["ถอดเสียง", "เขียนสรุป", "สรุปพร้อม"]
OUTPUTS = [("_executive.html", "สรุปผู้บริหาร", "อ่านจบใน 3 นาที ตัวเลขสำคัญครบ"),
           ("_detailed.html", "รายงานฉบับเต็ม", "ทุกหัวข้อ พร้อมภาพสไลด์จากคลิป"),
           ("_plain.html", "ฉบับข้อความล้วน", "ไม่มีดีไซน์ ก๊อปไปวางใน Word หรืออีเมลได้ทันที")]
MAX_ROWS = 6  # more rows push the window past a 1080p laptop screen at 150%
HINT = "วิดีโอหรือเสียง · ประชุมเดียวกันที่อัดไว้หลายไฟล์ ทยอยเพิ่มได้ แล้วค่อยกดเริ่มสรุป"
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


def part_order(paths):
    """Natural filename order, so "Recording 9" comes before "Recording 10"."""
    return sorted(paths, key=lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)])


def output_stem(medias) -> str:
    """One file -> its own stem; several parts of one meeting -> first part's stem + "_รวม"."""
    return medias[0].stem + ("_รวม" if len(medias) > 1 else "")


def remaining(hms: str) -> str:
    """"00:08:01" -> "ประมาณ 8 นาที", "01:05:00" -> "ประมาณ 1 ชม. 5 นาที"; under a minute -> "ไม่ถึง 1 นาที"."""
    h, m, _ = (int(x) for x in hms.split(":"))
    if not h and not m:
        return "ไม่ถึง 1 นาที"
    return f"ประมาณ {h} ชม. {m} นาที" if h else f"ประมาณ {m} นาที"


def dur_th(minutes: float) -> str:
    """75 -> "1 ชม. 15 นาที", 20 -> "20 นาที"."""
    h, m = divmod(max(1, round(minutes)), 60)
    return (f"{h} ชม. {m} นาที" if m else f"{h} ชม.") if h else f"{m} นาที"


def estimate(secs, x: float, claude_min=None):
    """Minutes (low, high) until the summary is ready.

    secs = media seconds still to transcribe; x = realtime factor of this machine (+30 s model load per file);
    Claude takes 5-15 min unless this machine has a measured time.
    """
    t = sum(secs) / x / 60 + 0.5 * len(secs)
    c_lo, c_hi = (claude_min * 0.8, claude_min * 1.3) if claude_min else (5, 15)
    return t + c_lo, t * 1.3 + c_hi


def estimate_th(lo: float, hi: float) -> str:
    end = lambda m: time.strftime("%H:%M", time.localtime(time.time() + m * 60))
    span = f"{round(lo)}–{round(hi)} นาที" if hi < 60 else f"{dur_th(lo)} – {dur_th(hi)}"
    return f"ใช้เวลาประมาณ {span} · เสร็จราว {end(lo)}–{end(hi)} น."


def load_speed() -> dict:
    """Measured speed from earlier runs, else a guess from the GPU the installer found."""
    try:
        return json.loads(SPEED.read_text(encoding="utf-8"))
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        return {"x": 15}
    if (HERE / "models" / "typhoon-whisper-turbo-ov").exists():  # installer fetches these only for Intel GPUs
        return {"x": 8}
    return {"x": 2}


def learn_speed(line: str, audio: dict):
    """Save this machine's realtime factor from transcribe.py's step timings (audio = per-file scratch dict)."""
    hms = lambda m: int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    if m := AUDIO_LEN.match(line):
        audio["secs"] = hms(m)
    elif (m := TRANSCRIBED.match(line)) and audio.get("secs") and hms(m) >= 5:  # < 5 s: rounding noise
        save_speed(x=round(audio["secs"] / hms(m), 1))


def save_speed(**kw):
    try:
        SPEED.write_text(json.dumps({**load_speed(), **kw}), encoding="utf-8")
    except OSError:
        pass  # estimate only; never fail a run over it


def media_seconds(path: Path):
    """Length of a recording in seconds; 0 if ffprobe can't read it (not a recording / broken);
    None if ffprobe itself didn't run, so a missing tool never blocks a run."""
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths(weak=True)
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                             creationflags=subprocess.CREATE_NO_WINDOW)  # stderr may hold a Thai path
    except Exception:
        return None
    try:
        return float(out.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


def fit(text: str, measure, width: int) -> str:
    """Cut the middle of a long name until measure(text) fits width, keeping the end (part number, extension).
    Measured, not counted: Thai and Latin letters differ in width; a too-wide label would widen the window."""
    if measure(text) <= width:
        return text
    head, tail = text[:-8], text[-8:]
    while head and measure(head + "…" + tail) > width:
        head = head[:-1]
    return head + "…" + tail


def transcript_of(media: Path) -> Path:
    return media.with_name(f"{media.stem}_transcript.txt")  # transcribe.py reuses it, so no time needed


def transcribe_status(line: str):
    """transcribe.py output line -> (Thai status text, fraction 0..1 or None), or None if not progress."""
    m = PCT.search(line)
    if m:
        pct, done, total, eta = m.groups()
        left = f" · เหลืออีก{remaining(eta)}" if int(pct) else ""
        return f"ถอดเสียงแล้ว {pct}% (ถึงนาทีที่ {done} จาก {total}){left}", int(pct) / 100
    m = STEP.match(line)
    return (STEP_TH[m.group(1)], None) if m else None


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
        # width=1: Canvas asks for 378 px by default, two side by side would widen the window; callers fill/expand
        super().__init__(parent, bg=parent["bg"], width=1, height=px(height), highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command, self.colors, self.dim, self.size = text, command, (fill, ink), dim, size
        self.enabled = True
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def restyle(self, text, fill, ink):
        self.text, self.colors = text, (fill, ink)
        self.draw()

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
        self.caption = tk.Label(h, text="ไฟล์ประชุม · ได้สรุป 3 ฉบับเปิดในเบราว์เซอร์", font=font(9), bg=INK, fg=DIM)
        self.caption.pack(anchor="w")
        self.file = tk.Label(h, text="ยังไม่ได้เลือกไฟล์", font=font(15, "bold"), bg=INK, fg="white",
                             anchor="w", justify="left")
        self.file.pack(fill="x", pady=(px(2), px(2)))
        self.rows = tk.Frame(h, bg=INK)  # picked files, one row each, until "เริ่มสรุป"
        h.bind("<Configure>", lambda e: self.file.configure(wraplength=e.width), add="+")
        self.hint = tk.Label(h, text=HINT, font=font(9), bg=INK, fg=DIM, anchor="w", justify="left", wraplength=px(400))
        self.hint.pack(fill="x")
        h.bind("<Configure>", lambda e: self.hint.configure(wraplength=e.width), add="+")
        self.btns = btns = tk.Frame(h, bg=INK)
        btns.pack(fill="x", pady=(px(18), 0))
        self.btn = Pill(btns, "เลือกไฟล์ประชุม", self.pick, fill="white", ink=INK, dim=("#2C2C2E", "#6B6B70"))
        self.btn.pack(side="left", fill="x", expand=True)
        self.go = Pill(btns, "เริ่มสรุป", self.begin, fill="white", ink=INK, dim=("#2C2C2E", "#6B6B70"))
        self.name_font = tkfont.Font(font=font(11, "bold"))
        self.pending, self.secs = [], {}  # files waiting for "เริ่มสรุป"; media seconds per file (probed in background)

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
        self.status = tk.Label(p, text="เลือกไฟล์ แล้วกดเริ่มสรุป", font=font(10), bg=CARD, fg=MUTED,
                               anchor="w", justify="left")
        self.status.pack(fill="x")
        p.bind("<Configure>", lambda e: self.status.configure(wraplength=e.width), add="+")

        self.results = Card(page, CARD, radius=20, pad=5)  # filled with one row per summary when done
        self.foot = tk.Frame(page, bg=BG)
        self.foot.pack(fill="x", pady=(px(12), 0))
        self.toggle = link(self.foot, "ดูรายละเอียด ▾", self.toggle_log)
        self.toggle.pack(side="left")
        tk.Label(self.foot, text=f"v{APP_VERSION}", font=font(9), bg=BG, fg=DIM).pack(side="right", padx=(px(12), 0))
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

    def keep_on_screen(self):
        """Windows opens the window part-way down; when it grows (results, file rows) lift it so the bottom
        stays above the taskbar instead of hiding the footer."""
        r = self.root
        r.update_idletasks()
        try:
            from ctypes import byref, windll, wintypes
            area = wintypes.RECT()
            windll.user32.SystemParametersInfoW(48, 0, byref(area), 0)  # SPI_GETWORKAREA: screen minus taskbar
            bottom = area.bottom
        except Exception:
            bottom = r.winfo_screenheight() - px(48)
        over = r.winfo_rooty() + r.winfo_height() + px(8) - bottom
        if over > 0:
            r.geometry(f"+{r.winfo_x()}+{max(0, r.winfo_y() - over)}")

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
        self.root.after_idle(self.keep_on_screen)

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
            elif kind == "secs":
                self.secs[val[0]] = val[1]
                self.render_pending()
            elif kind == "end":
                ok, msg, files = val
                self.creeping = self.running = False
                self.btn.set_enabled(True)
                if ok:
                    self.pending = []  # next pick starts a new meeting; on failure the list stays for a retry
                self.render_pending()  # before the badge: an empty list resets it to "idle"
                self.badge.set("ok" if ok else "fail")
                self.status.configure(text=msg, fg=INK if ok else "#D93A3A")
                if self.root.state() == "iconic":  # something minimized us while Claude worked
                    self.root.deiconify()
                self.root.lift()
                if ok:
                    self.hint.pack_forget()  # results card is tall: keep the footer on a 1080p laptop at 150%
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
        fs = filedialog.askopenfilenames(title="เลือกไฟล์ประชุม (ประชุมเดียวกันเลือกได้หลายไฟล์)", filetypes=[
            ("คลิปประชุม", "*.mp4 *.mov *.mkv *.webm *.mp3 *.m4a *.wav"), ("ทุกไฟล์", "*.*")])
        if fs:
            self.add([Path(f) for f in fs])

    def add(self, medias):
        """Queue files (more picks append, duplicates ignored); nothing runs until "เริ่มสรุป"."""
        known = {m.resolve() for m in self.pending}
        new = [m for m in medias if m.resolve() not in known]
        if not self.running and self.results.winfo_ismapped():  # a new meeting after a finished one
            self.results.pack_forget()
            self.reveal.pack_forget()
            self.steps.reset()
            self.status.configure(text="เลือกไฟล์ แล้วกดเริ่มสรุป", fg=MUTED)
            self.status.pack(fill="x")
            self.hint.pack(fill="x", before=self.btns)
        self.pending = part_order(self.pending + new)
        for m in new:
            threading.Thread(target=lambda m=m: self.q.put(("secs", (m, media_seconds(m)))), daemon=True).start()
        self.render_pending()

    def remove(self, media):
        self.pending.remove(media)
        self.render_pending()

    def render_pending(self):
        """Hero card: file rows + time estimate + "เริ่มสรุป" while files wait; one name line otherwise."""
        for w in self.rows.winfo_children():
            w.destroy()
        if self.running or not self.pending:
            self.rows.pack_forget()
            self.go.pack_forget()
            self.file.pack(fill="x", pady=(px(2), px(2)), after=self.caption)  # hint may be hidden (done state)
            self.btn.restyle("เลือกไฟล์ประชุม", "white", INK)
            if not self.running:
                self.hint.configure(text=HINT)
                self.badge.set("idle")
            return
        self.badge.set("ready")
        self.file.pack_forget()
        self.rows.pack(fill="x", pady=(px(6), px(6)), after=self.caption)
        shown = self.pending if len(self.pending) <= MAX_ROWS else self.pending[:MAX_ROWS - 1]
        for i, m in enumerate(shown):
            row = tk.Frame(self.rows, bg=INK)
            row.pack(fill="x", pady=px(2))
            x = link(row, "✕", lambda m=m: self.remove(m))
            x.configure(bg=INK, fg=DIM, font=font(11))
            x.base = DIM
            x.bind("<Enter>", lambda e, x=x: x.configure(fg="white"))
            x.pack(side="right", padx=(px(10), 0))
            s = self.secs.get(m)
            length = "…" if m not in self.secs else "?" if s is None else "เปิดไม่ได้" if not s else                 time.strftime("%H:%M:%S", time.gmtime(s))
            tk.Label(row, text=length, font=font(9), bg=INK, fg="#FF8A8A" if s == 0 else DIM).pack(side="right")
            name = f"{i + 1}. {m.name}" if len(self.pending) > 1 else m.name
            tk.Label(row, text=fit(name, self.name_font.measure, px(290)), font=self.name_font,
                     bg=INK, fg="white", anchor="w").pack(side="left", fill="x", expand=True)
        if len(shown) < len(self.pending):
            tk.Label(self.rows, text=f"…และอีก {len(self.pending) - len(shown)} ไฟล์ (ลบไฟล์ด้านบนเพื่อดูไฟล์ถัดไป)",
                     font=font(9), bg=INK, fg=DIM, anchor="w").pack(fill="x", pady=px(2))
        self.hint.configure(text=self.estimate_text())
        self.btn.restyle("+ เพิ่มไฟล์", "#2C2C2E", "white")
        self.go.restyle(f"เริ่มสรุป ({len(self.pending)} ไฟล์)" if len(self.pending) > 1 else "เริ่มสรุป", "white", INK)
        # estimate first (ffprobe takes ~1 s); a file ffprobe can't open would only fail later in transcription
        self.go.set_enabled(all(m in self.secs and self.secs[m] != 0 for m in self.pending))
        self.go.pack(side="left", fill="x", expand=True, padx=(px(10), 0))
        self.root.after_idle(self.keep_on_screen)

    def estimate_text(self) -> str:
        if any(m not in self.secs for m in self.pending):
            return "กำลังคำนวณเวลาที่ใช้…"
        if any(self.secs[m] == 0 for m in self.pending):
            return "ไฟล์ที่ขึ้นว่า “เปิดไม่ได้” ไม่ใช่คลิปเสียง/วิดีโอ หรือไฟล์เสีย กด ✕ ลบออกก่อนเริ่ม"
        todo = [self.secs[m] for m in self.pending if not transcript_of(m).exists()]
        speed = load_speed()
        unknown = " (บางไฟล์ไม่รู้ความยาว เวลาจริงอาจนานกว่านี้)" if None in todo else ""
        todo = [t for t in todo if t]
        many = " · ทุกไฟล์รวมเป็นประชุมเดียว" if len(self.pending) > 1 else ""
        return estimate_th(*estimate(todo, speed["x"], speed.get("claude_min"))) + unknown + many

    def begin(self):
        if self.running or not self.go.enabled:  # durations still loading, or a file that can't be opened
            return
        if self.account is not None and not self.logged_in():
            return self.auth_action()
        self.start(self.pending)

    def start(self, medias):
        medias = part_order(medias)
        self.running = True
        self.render_pending()
        self.btn.set_enabled(False)
        self.results.pack_forget()
        self.status.pack(fill="x")
        self.reveal.pack_forget()
        self.file.configure(text=medias[0].name + (f"  + อีก {len(medias) - 1} ไฟล์" if len(medias) > 1 else ""))
        self.hint.configure(text=self.estimate_text() if self.pending else HINT)
        self.badge.set("run")
        self.steps.reset()
        self.steps.set(0, 0)
        threading.Thread(target=self.work, args=(medias,), daemon=True).start()

    # --- worker-thread side -----------------------------------------------------------------
    def work(self, medias):
        say = lambda kind, val=None: self.q.put((kind, val))
        try:
            n = len(medias)
            for i, media in enumerate(medias):
                part = f"ไฟล์ {i + 1}/{n} · " if n > 1 else ""
                say("log", f"ไฟล์ {i + 1}/{n}: {media}")
                say("status", part + "กำลังถอดเสียงและเก็บภาพสไลด์ในเครื่องนี้…")

                audio = {}

                def on_transcribe(line, i=i, part=part, audio=audio):
                    say("log", line)
                    learn_speed(line, audio)
                    st = transcribe_status(line)
                    if st:
                        say("status", part + st[0])
                        if st[1] is not None:  # one bar across all parts
                            say("step", (0, (i + st[1]) / n))

                frames = threading.Thread(target=run, args=([str(PY), str(HERE / "frames.py"), str(media)],
                                                            lambda l: say("log", l)))
                frames.start()
                cmd = [str(PY), str(HERE / "transcribe.py"), str(media)]
                code = run(cmd, on_transcribe)
                if code not in (0, 1):  # 1 = handled error with a message; anything else = native crash (GPU driver etc.)
                    say("log", f"transcribe.py crashed (exit {code}); retrying on CPU")
                    say("status", part + "ลองถอดเสียงใหม่อีกครั้งแบบไม่ใช้การ์ดจอ…")
                    code = run(cmd + ["--cpu", "--force"], on_transcribe)
                frames.join()
                if code:
                    say("log", f"transcribe.py exit {code}")
                    return say("end", (False, part + "ถอดเสียงไม่สำเร็จ กด “ดูรายละเอียด” เพื่อดูสาเหตุ", None))

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

            stem = output_stem(medias)
            t0 = time.time()
            prompt = PROMPT.format(path=medias[0]) if n == 1 else PROMPT_PARTS.format(
                n=n, stem=stem, paths="\n".join(f"{i + 1}. {m}" for i, m in enumerate(medias)))
            run([claude_exe(), "-p", prompt, "--output-format", "stream-json", "--verbose",
                 "--permission-mode", "acceptEdits", "--allowedTools", *CLAUDE_TOOLS],
                on_claude, cwd=str(medias[0].parent))
            files = [(medias[0].with_name(stem + suffix), title, desc) for suffix, title, desc in OUTPUTS]
            files = [f for f in files if f[0].exists()]
            if result.get("is_error") or not files:
                return say("end", (False, "Claude ทำงานไม่สำเร็จ ตรวจว่ามุมขวาบนเข้าสู่ระบบอยู่ แล้วลองใหม่อีกครั้ง", None))
            save_speed(claude_min=(time.time() - t0) / 60)
            say("end", (True, "กดเลือกฉบับที่ต้องการ จะเปิดในเบราว์เซอร์", files))
        except FileNotFoundError as e:  # claude.exe missing or removed after install
            say("log", repr(e))
            say("end", (False, "ไม่พบโปรแกรม Claude Code ในเครื่องนี้ ดับเบิลคลิก Install.bat อีกครั้งเพื่อติดตั้ง", None))
        except Exception as e:  # show anything unexpected instead of dying silently (pythonw has no console)
            say("log", repr(e))
            say("end", (False, f"เกิดข้อผิดพลาด: {e}", None))


if __name__ == "__main__" and sys.argv[1:] == ["--selftest"]:
    bar = "[4/4] Transcribe ████████░░░░  58%  01:45:12 / 03:01:07  elapsed 00:11:02  ETA ~00:08:01"
    assert transcribe_status(bar) == ("ถอดเสียงแล้ว 58% (ถึงนาทีที่ 01:45:12 จาก 03:01:07) · เหลืออีกประมาณ 8 นาที", .58)
    assert transcribe_status(bar.replace(" 58%", "  0%"))[0].endswith("03:01:07)")  # no ETA yet at 0%
    assert transcribe_status("[2/4] Detect language ...") == (STEP_TH["Detect language"], None)
    assert transcribe_status("[2/4] Detect language ... done (00:00:05)  th (forced)") is None
    assert transcribe_status("REUSED existing transcript: x.txt") is None
    assert remaining("01:05:59") == "ประมาณ 1 ชม. 5 นาที" and remaining("00:00:40") == "ไม่ถึง 1 นาที"
    names = ["Rec 10.m4a", "Rec 9.m4a", "rec 2b.m4a"]
    assert [p.name for p in part_order([Path(x) for x in names])] == ["rec 2b.m4a", "Rec 9.m4a", "Rec 10.m4a"]
    assert output_stem([Path("a/x.m4a")]) == "x" and output_stem([Path("a/x.m4a"), Path("a/y.m4a")]) == "x_รวม"
    assert [round(m, 2) for m in estimate([600], 2)] == [10.5, 22.15] and estimate([], 2, 10) == (8, 13)  # 10-min clip on CPU; all reused
    import tempfile
    SPEED = Path(tempfile.mkdtemp()) / "speed.json"
    scratch = {}
    for line in ["[1/4] Extract audio ... done (00:00:01)  00:12:53 of audio", "[4/4] Transcribe ███ 100%  x",
                 "[4/4] Transcribe ... done (00:01:29)"]:
        learn_speed(line, scratch)
    assert load_speed()["x"] == 8.7, load_speed()  # 773 s of audio in 89 s
    assert fit("a.m4a", len, 42) == "a.m4a" and fit("x" * 60 + ".mp4", len, 42) == "x" * 33 + "…" + "x" * 4 + ".mp4"
    assert dur_th(20) == "20 นาที" and dur_th(75) == "1 ชม. 15 นาที" and dur_th(120) == "2 ชม."
    assert estimate_th(8, 21).startswith("ใช้เวลาประมาณ 8–21 นาที · เสร็จราว ")
    assert estimate_th(50, 95).startswith("ใช้เวลาประมาณ 50 นาที – 1 ชม. 35 นาที")
    print("selftest ok")
elif __name__ == "__main__":
    try:  # crisp text on scaled (125%/150%) laptop screens instead of bitmap-stretched blur
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("meeting-summary")  # taskbar shows our icon, not Python's
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    dropped = [Path(a) for a in sys.argv[1:] if Path(a).is_file()]  # files dropped onto the desktop shortcut
    if dropped:
        root.after(300, app.add, dropped)  # wait for "เริ่มสรุป": more parts may follow
    root.mainloop()
