"""Grab a still every time the picture changes (slide flips, screen shares) from a meeting video.

Usage: frames.py <video file> [--threshold 0.01] [--force]
Writes <stem>_frames/<HH-MM-SS>.jpg next to the input, 4x4 contact sheets sheet_NNN.jpg, and
index.txt (one "HH:MM:SS  file  sheet_NNN.jpg rXcY" per line).
Audio-only files are skipped. Decodes keyframes only, so a 3 h 1080p recording takes about a minute.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

from transcribe import Progress, ts

# Low on purpose: recall over precision. Near-duplicates are cheap; the summary step picks the few
# frames that match key points. 0.03 missed slide flips in a Teams recording; 0.008 kept every one.
DEFAULT_THRESHOLD = 0.01
SHEET_COLS = 4
PTS = re.compile(rb"pts_time:([0-9.]+)")
CLOCK = re.compile(rb"time=(\d+):(\d+):(\d+\.?\d*)")


def probe(path: Path):
    """-> (has_video, duration_seconds)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                          "-of", "default=nw=1", str(path)], capture_output=True, text=True).stdout
    dur = re.search(r"duration=([0-9.]+)", out)
    return "codec_type=video" in out, float(dur.group(1)) if dur else 0.0


def stamp_name(sec: float) -> str:
    return ts(sec).replace(":", "-") + ".jpg"


def sheet_cell(i: int) -> str:
    """0-based frame index -> 'sheet_003.jpg r2c4' (1-based row/col on that contact sheet)."""
    per = SHEET_COLS * SHEET_COLS
    pos = i % per
    return f"sheet_{i // per + 1:03d}.jpg r{pos // SHEET_COLS + 1}c{pos % SHEET_COLS + 1}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="ffmpeg scene score, 0-1")
    ap.add_argument("--force", action="store_true", help="re-extract even if the frames folder exists")
    args = ap.parse_args()

    import static_ffmpeg

    static_ffmpeg.add_paths(weak=True)
    src = Path(args.file.strip().strip('"').strip("'")).expanduser().resolve()
    if not src.is_file():
        sys.exit(f"File not found: {src}")
    out_dir = src.with_name(f"{src.stem}_frames")
    index = out_dir / "index.txt"
    if index.exists() and not args.force:
        print(f"REUSED existing frames: {out_dir}")
        return
    has_video, duration = probe(src)
    if not has_video:
        print("No video track: skipping frame capture.")
        return

    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.jpg"):  # stale frames/sheets from an earlier run
        old.unlink()
    prog = Progress(1)
    prog.step(1, "Capture slides")
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-skip_frame", "nokey", "-i", str(src), "-an",
           "-vf", f"select='gt(scene,{args.threshold})+eq(n,0)',scale=1280:-2,showinfo",
           "-fps_mode", "vfr", "-q:v", "4", str(out_dir / "tmp_%05d.jpg")]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    stamps, buf = [], b""
    while chunk := proc.stderr.read(4096):
        buf += chunk
        *lines, buf = re.split(rb"[\r\n]", buf)
        for line in lines:
            if m := PTS.search(line):
                stamps.append(float(m.group(1)))
            elif m := CLOCK.search(line):
                h, mi, s = m.groups()
                prog.bar(int(h) * 3600 + int(mi) * 60 + float(s), duration)
    if proc.wait() != 0:
        sys.exit(f"ffmpeg failed (exit {proc.returncode})")

    tmp = sorted(out_dir.glob("tmp_*.jpg"))
    if len(tmp) != len(stamps):  # never mislabel a slide with the wrong time
        sys.exit(f"frame/timestamp mismatch: {len(tmp)} files vs {len(stamps)} stamps")
    # Contact sheets (4x4 thumbnails, row by row) so the summary step can scan every frame in a few images.
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(out_dir / "tmp_%05d.jpg"),
                    "-vf", f"scale=480:-2,tile={SHEET_COLS}x{SHEET_COLS}", "-q:v", "5",
                    str(out_dir / "sheet_%03d.jpg")], check=True)
    rows = []
    for i, (f, sec) in enumerate(zip(tmp, stamps)):
        name = stamp_name(sec)
        if (out_dir / name).exists():  # two changes within the same second
            name = name.replace(".jpg", f"_{f.stem[-5:]}.jpg")
        f.replace(out_dir / name)
        rows.append(f"{ts(sec)}  {name}  {sheet_cell(i)}")
    index.write_text("\n".join(rows) + "\n", encoding="utf-8")
    prog.bar(duration, duration)
    prog.done(f"{len(rows)} frames")
    print(f"Frames:     {out_dir}  ({len(rows)} frames, index.txt)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        assert stamp_name(1092.0) == "00-18-12.jpg"
        assert sheet_cell(0) == "sheet_001.jpg r1c1"
        assert sheet_cell(15) == "sheet_001.jpg r4c4"
        assert sheet_cell(21) == "sheet_002.jpg r2c2"
        assert PTS.search(b"[Parsed_showinfo_2] n: 3 pts: 1092 pts_time:1092.5 duration").group(1) == b"1092.5"
        assert CLOCK.search(b"frame= 30 fps=3 q=4.0 size=N/A time=01:02:05.40 bitrate=N/A").groups() == (b"01", b"02", b"05.40")
        print("selftest ok")
    else:
        main()
