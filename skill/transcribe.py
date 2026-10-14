"""Local meeting transcription: Typhoon Whisper Turbo (Thai) / Whisper large-v3-turbo (other).

Usage: transcribe.py <media file> [--lang auto|th|en|<code>] [--speakers] [--force]
Writes <stem>_transcript.txt next to the input; reuses it if it already exists.

Engine order: NVIDIA CUDA (faster-whisper) -> Intel GPU (OpenVINO) -> CPU int8 (faster-whisper).
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SR = 16000
MODELS = Path(__file__).resolve().parent / "models"
TYPHOON = MODELS / "typhoon-whisper-turbo"          # CTranslate2 (faster-whisper)
WHISPER = MODELS / "whisper-large-v3-turbo"
TYPHOON_OV = MODELS / "typhoon-whisper-turbo-ov"    # OpenVINO (Intel GPU)
WHISPER_OV = MODELS / "whisper-large-v3-turbo-ov"
OV_CACHE = MODELS / "ov_cache"                      # compiled GPU kernels: first load ~17 s, then ~4 s
TYPHOON_NAME = "Typhoon Whisper Turbo (typhoon-ai/typhoon-whisper-turbo)"
WHISPER_NAME = "Whisper large-v3-turbo"
PROBE_SECONDS = 15
PROBE_POINTS = (0.10, 0.50, 0.80)
MIN_CONFIDENCE = 0.5
# Thai is token-heavy: a 30 s window can exceed Whisper's ~448-token decode limit and the tail
# is silently dropped (verified on a test clip). 20 s keeps every sentence; English stays at 30 s.
CHUNK_SECONDS = {"th": 20}


def load_audio(path: Path) -> np.ndarray:
    """Decode any media file to 16 kHz mono float32 via ffmpeg (list args: spaces/Thai paths are safe)."""
    import static_ffmpeg

    static_ffmpeg.add_paths(weak=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn",
           "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        sys.exit(f"ffmpeg failed: {out.stderr.decode('utf-8', 'replace').strip()}")
    audio = np.frombuffer(out.stdout, np.float32)
    if audio.size == 0:
        sys.exit("No audio track found in file.")
    return audio


def probe_clips(audio: np.ndarray):
    """3 short clips at 10/50/80% of the recording, not just the start."""
    n = PROBE_SECONDS * SR
    for point in PROBE_POINTS:
        start = max(0, min(int(len(audio) * point), len(audio) - n))
        yield audio[start:start + n]


def pick_language(votes):
    """votes = [(lang, prob or None), ...] from the probe clips -> (lang, use_typhoon).

    Thai anywhere, disagreement between clips, or low confidence -> Typhoon (Thai / mixed / unsure).
    """
    langs = {lang for lang, _ in votes}
    probs = [p for _, p in votes if p is not None]
    if "th" in langs or len(langs) > 1 or (probs and min(probs) < MIN_CONFIDENCE):
        return "th", True
    return langs.pop(), False


def merge_windows(segments, max_samples):
    """Greedily join consecutive VAD speech segments into windows spanning <= max_samples."""
    windows = []
    for seg in segments:
        if windows and seg["end"] - windows[-1][0] <= max_samples:
            windows[-1][1] = seg["end"]
        else:
            windows.append([seg["start"], seg["end"]])
    return windows


def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class Progress:
    """`[n/N] step` lines plus a bar with % and ETA on stdout, flushed so a background log is live."""

    def __init__(self, total_steps):
        self.total = total_steps

    def step(self, n, label):
        self.n, self.label, self.t0, self.last = n, label, time.perf_counter(), -1
        print(f"[{n}/{self.total}] {label} ...", flush=True)

    def done(self, note=""):
        took = time.perf_counter() - self.t0
        print(f"[{self.n}/{self.total}] {self.label} ... done ({ts(took)}){'  ' + note if note else ''}", flush=True)

    def bar(self, done, total, width=24, every=2):
        """done/total in media seconds; prints at most once per `every` percent."""
        pct = min(100, int(100 * done / total)) if total else 100
        if pct == self.last or (pct < self.last + every and pct < 100):
            return
        self.last = pct
        elapsed = time.perf_counter() - self.t0
        eta = elapsed / done * (total - done) if done else 0
        fill = width * pct // 100
        print(f"[{self.n}/{self.total}] {self.label} {'█' * fill}{'░' * (width - fill)} {pct:3d}%  "
              f"{ts(done)} / {ts(total)}  elapsed {ts(elapsed)}  ETA ~{ts(eta)}", flush=True)


def run_openvino(audio, forced_lang, prog):
    """Intel GPU via OpenVINO GenAI. Greedy decoding only (beam search is not implemented on GPU)."""
    import openvino as ov
    import openvino_genai as og
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if "GPU" not in ov.Core().available_devices:
        raise RuntimeError("no Intel GPU visible to OpenVINO")

    def load(path):
        return og.WhisperPipeline(str(path), "GPU", CACHE_DIR=str(OV_CACHE))

    prog.step(2, "Detect language")
    whisper = None
    if forced_lang:
        lang, use_typhoon, detected = forced_lang, forced_lang == "th", "forced"
    else:
        whisper = load(WHISPER_OV)
        cfg = whisper.get_generation_config()
        cfg.max_new_tokens = 1  # only the language token is needed
        votes = [(whisper.generate(c.tolist(), cfg).language, None) for c in probe_clips(audio)]
        lang, use_typhoon = pick_language(votes)
        detected = ", ".join(l for l, _ in votes)
    prog.done(f"{lang} ({detected})")

    prog.step(3, "Load model")
    pipe = load(TYPHOON_OV) if use_typhoon else whisper or load(WHISPER_OV)
    cfg = pipe.get_generation_config()
    cfg.language, cfg.task, cfg.max_new_tokens = f"<|{lang}|>", "transcribe", 440
    prog.done(TYPHOON_NAME if use_typhoon else WHISPER_NAME)

    prog.step(4, "Transcribe")
    duration = len(audio) / SR
    max_s = CHUNK_SECONDS.get(lang, 30)
    speech = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=max_s, min_silence_duration_ms=160))
    lines = []
    for start, end in merge_windows(speech, max_s * SR):
        text = pipe.generate(audio[start:end].tolist(), cfg).texts[0].strip()
        if text:
            lines.append(f"[{ts(start / SR)} - {ts(end / SR)}] {text}")
        prog.bar(end / SR, duration)
    prog.bar(duration, duration)
    prog.done()
    return (TYPHOON_NAME if use_typhoon else WHISPER_NAME), "intel-gpu/openvino-fp16", lang, detected, lines


def run_faster_whisper(audio, forced_lang, device, prog):
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    opts = dict(device=device, compute_type=compute, cpu_threads=os.cpu_count() or 4)

    prog.step(2, "Detect language")
    whisper = None
    if forced_lang:
        lang, use_typhoon, detected = forced_lang, forced_lang == "th", "forced"
    else:
        whisper = WhisperModel(str(WHISPER), **opts)
        votes = [whisper.detect_language(audio=c)[:2] for c in probe_clips(audio)]
        lang, use_typhoon = pick_language(votes)
        detected = ", ".join(f"{l}:{p:.2f}" for l, p in votes)
    prog.done(f"{lang} ({detected})")

    prog.step(3, "Load model")
    model = WhisperModel(str(TYPHOON), **opts) if use_typhoon else whisper or WhisperModel(str(WHISPER), **opts)
    prog.done(TYPHOON_NAME if use_typhoon else WHISPER_NAME)

    prog.step(4, "Transcribe")
    duration = len(audio) / SR
    # Batched pipeline: VAD splits audio into <=30 s (Thai: 20 s) chunks, decoded in parallel.
    segments, _ = BatchedInferencePipeline(model=model).transcribe(
        audio, language=lang, task="transcribe", batch_size=8,
        chunk_length=CHUNK_SECONDS.get(lang, 30), beam_size=5)
    lines = []
    for s in segments:  # lazy generator: decoding happens while iterating
        lines.append(f"[{ts(s.start)} - {ts(s.end)}] {s.text.strip()}")
        prog.bar(s.end, duration)
    prog.bar(duration, duration)
    prog.done()
    return (TYPHOON_NAME if use_typhoon else WHISPER_NAME), f"{device}/{compute}", lang, detected, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--lang", default="auto", help="auto (default), th, en, or any Whisper language code")
    ap.add_argument("--speakers", action="store_true", help="who-said-what (needs pyannote + HF_TOKEN)")
    ap.add_argument("--force", action="store_true", help="re-transcribe even if transcript exists")
    args = ap.parse_args()

    src = Path(args.file.strip().strip('"').strip("'")).expanduser().resolve()
    if not src.is_file():
        sys.exit(f"File not found: {src}")
    out = src.with_name(f"{src.stem}_transcript.txt")
    if out.exists() and not args.force:
        print(f"REUSED existing transcript: {out}")
        return

    if args.speakers:
        # ponytail: diarization not installed yet; add pyannote.audio + HF_TOKEN when needed
        print("WARNING: --speakers needs pyannote.audio and an HF_TOKEN (not set up yet). Continuing without speakers.")

    import ctranslate2

    t0 = time.perf_counter()
    prog = Progress(4)
    prog.step(1, "Extract audio")
    audio = load_audio(src)
    duration = len(audio) / SR
    prog.done(f"{ts(duration)} of audio")
    forced = None if args.lang == "auto" else args.lang

    if ctranslate2.get_cuda_device_count() > 0:
        result = run_faster_whisper(audio, forced, "cuda", prog)
    else:
        try:
            result = run_openvino(audio, forced, prog)
        except Exception as e:  # driver/runtime problems must not block a transcript
            print(f"WARNING: Intel GPU path failed ({e}); falling back to CPU.")
            result = run_faster_whisper(audio, forced, "cpu", prog)
    name, engine, lang, detected, lines = result
    elapsed = time.perf_counter() - t0

    header = [f"# Source: {src.name}", f"# Model: {name} [{engine}]",
              f"# Language: {lang} (detected: {detected})", f"# Duration: {ts(duration)}", ""]
    tmp = out.with_suffix(".txt.tmp")
    tmp.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    tmp.replace(out)  # atomic: a crashed run never leaves a half transcript that gets reused

    print(f"Model:      {name} [{engine}]")
    print(f"Language:   {lang} (probes: {detected})")
    print(f"Audio:      {ts(duration)}  |  Processing time: {elapsed:.1f}s  ({duration / elapsed:.1f}x realtime)")
    print(f"Transcript: {out}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        assert pick_language([("en", .9), ("en", .8), ("en", .95)]) == ("en", False)
        assert pick_language([("ja", .9), ("ja", .8), ("ja", .7)]) == ("ja", False)
        assert pick_language([("en", .9), ("th", .8), ("en", .9)]) == ("th", True)
        assert pick_language([("en", .9), ("en", .3), ("en", .9)]) == ("th", True)
        assert pick_language([("en", .9), ("ja", .8), ("en", .9)]) == ("th", True)
        assert pick_language([("en", None)] * 3) == ("en", False)
        segs = [{"start": 0, "end": 5}, {"start": 6, "end": 9}, {"start": 12, "end": 20}, {"start": 21, "end": 22}]
        assert merge_windows(segs, 10) == [[0, 9], [12, 22]]
        assert merge_windows([], 10) == []
        assert ts(3725.9) == "01:02:05"
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            p = Progress(4)
            p.step(4, "Transcribe")
            for sec in range(0, 101):
                p.bar(sec, 100)
            p.bar(100, 100)
        bars = [l for l in buf.getvalue().splitlines() if "%" in l]
        assert len(bars) == 51 and bars[-1].count(" 100%") == 1, len(bars)  # every 2% + no duplicate 100%
        print("selftest ok")
    else:
        main()
