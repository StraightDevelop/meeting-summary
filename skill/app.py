"""Small window around the meeting-summary skill for people who never open a terminal.

Open it from the desktop shortcut, then pick a recording (or drop the file onto the shortcut).
It runs transcribe.py + frames.py locally, then asks Claude Code (`claude -p`, the user's own
login) to run the rest of SKILL.md, and finally opens the folder with the .eml selected.
"""
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "Scripts" / "python.exe"
FONT = ("Leelawadee UI", 11)
PCT = re.compile(r"Transcribe .*?(\d+)%")
PROMPT = ("Use the meeting-summary skill on this recording: {path}\n"
          "Step 1 (transcript + slide frames) has already been run next to the file; continue from step 2. "
          "Nobody is available to answer questions, so run every remaining step to the end.")
CLAUDE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "PowerShell"]


def claude_exe() -> str:
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")


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


class App:
    def __init__(self, root: tk.Tk):
        self.root, self.q = root, queue.Queue()
        root.title("สรุปประชุม")
        tk.Label(root, text="สรุปประชุมจากไฟล์คลิป", font=("Leelawadee UI", 16, "bold")).pack(pady=(16, 4))
        tk.Label(root, text="เลือกไฟล์วิดีโอ/เสียงของการประชุม แล้วรอจนเสร็จ (คลิปยาวอาจใช้เวลาเป็นชั่วโมง)",
                 font=FONT, wraplength="15c", justify="center").pack(padx=16)
        self.btn = tk.Button(root, text="เลือกไฟล์ประชุม…", font=("Leelawadee UI", 13), padx=16, pady=6,
                             command=self.pick)
        self.btn.pack(pady=12)
        self.status = tk.Label(root, text="", font=FONT)
        self.status.pack()
        self.bar = ttk.Progressbar(root, length="15c", maximum=100)
        self.bar.pack(pady=6)
        self.log = tk.Text(root, height=12, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        root.after(100, self.pump)

    # --- UI-thread side ---------------------------------------------------------------------
    def pump(self):
        while not self.q.empty():
            kind, val = self.q.get()
            if kind == "log":
                self.log.configure(state="normal")
                self.log.insert("end", val + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
            elif kind == "status":
                self.status.configure(text=val)
            elif kind == "pct":
                self.bar.configure(mode="determinate", value=val)
            elif kind == "busy":
                self.bar.configure(mode="indeterminate")
                self.bar.start(15)
            elif kind == "end":
                self.bar.stop()
                self.btn.configure(state="normal")
                ok, msg = val
                (messagebox.showinfo if ok else messagebox.showerror)("สรุปประชุม", msg)
        self.root.after(100, self.pump)

    def pick(self):
        f = filedialog.askopenfilename(title="เลือกไฟล์ประชุม", filetypes=[
            ("คลิปประชุม", "*.mp4 *.mov *.mkv *.webm *.mp3 *.m4a *.wav"), ("ทุกไฟล์", "*.*")])
        if f:
            self.start(Path(f))

    def start(self, media: Path):
        self.btn.configure(state="disabled")
        self.bar.configure(value=0)
        threading.Thread(target=self.work, args=(media,), daemon=True).start()

    # --- worker-thread side -----------------------------------------------------------------
    def work(self, media: Path):
        say = lambda kind, val=None: self.q.put((kind, val))
        try:
            say("log", f"ไฟล์: {media}")
            say("status", "ขั้นที่ 1/2 · ถอดเสียงและเก็บภาพสไลด์…")

            def on_transcribe(line):
                say("log", line)
                m = PCT.search(line)
                if m:
                    say("pct", int(m.group(1)))

            frames = threading.Thread(target=run, args=([str(PY), str(HERE / "frames.py"), str(media)],
                                                        lambda l: say("log", l)))
            frames.start()
            code = run([str(PY), str(HERE / "transcribe.py"), str(media)], on_transcribe)
            frames.join()
            if code:
                return say("end", (False, "ถอดเสียงไม่สำเร็จ ดูรายละเอียดในกล่องข้อความ"))

            say("status", "ขั้นที่ 2/2 · Claude กำลังเขียนสรุปและอีเมล (ประมาณ 5–15 นาที)…")
            say("busy")
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
            eml = media.with_name(f"{media.stem}_executive.eml")
            if result.get("is_error") or not eml.exists():
                return say("end", (False, "Claude ทำงานไม่สำเร็จ ถ้าเพิ่งติดตั้ง ลองเปิด Install.bat อีกครั้งเพื่อ login Claude"))
            subprocess.run(["explorer", f"/select,{eml}"])
            say("pct", 100)
            say("status", "เสร็จแล้ว")
            say("end", (True, f"เสร็จแล้ว\n\nดับเบิลคลิกไฟล์ {eml.name} เพื่อเปิดอีเมล → ใส่ผู้รับ → ส่ง"))
        except Exception as e:  # show anything unexpected instead of dying silently (pythonw has no console)
            say("log", repr(e))
            say("end", (False, f"เกิดข้อผิดพลาด: {e}"))


if __name__ == "__main__":
    try:  # crisp text on scaled (125%/150%) laptop screens instead of bitmap-stretched blur
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():  # file dropped onto the desktop shortcut
        root.after(300, app.start, Path(sys.argv[1]))
    root.mainloop()
