# Handover — 2026-10-15 (afternoon)

Branch `main`. Repo: https://github.com/StraightDevelop/meeting-summary (public)
Pushed: `f6a7ef1` tag `v1.1.0`. Local, NOT pushed yet: v1.1.1 commit (waits on model upload below).

## Done
- **Boss's error fixed (v1.1.0, pushed):** on CPU, faster-whisper `batch_size=8` overflowed ctranslate2's OpenMP
  worker stack on Windows → exit 127, no output, log stopped at "[4/4] Transcribe ...". Every installed
  machine without NVIDIA hit it (installer never shipped the OpenVINO models, so all fell to CPU).
  Repro: `transcribe.py "<file>" --cpu --force` with batch 8. Batch 6 crashes, 4/2/1 pass; now `CPU_BATCH = 2`.
- App: status line shows step + `ถอดเสียงแล้ว N% (ถึงนาทีที่ … จาก …) · เหลืออีก…`; retries once with
  `--cpu --force` on a native crash (exit not 0/1) and logs the exit code; clear Thai message if claude.exe missing.
- Installer (v1.1.1, local): downloads the `*-ov` models only when an Intel GPU is present; a failed
  download is skipped with a warning (CPU still works). Tested the 404 skip path.
- Tested on this machine: full 12:53 Thai m4a on CPU (6m16s, 2.1x) and Intel GPU (1m29s, 8.7x); app window
  end-to-end with real Claude on a 2-min clip (3 HTML produced in ~5 min); simulated-crash retry.
  Driver used: scratchpad `drv/drive.py` (not in repo).

## Next steps
1. `gh auth login`, then create releases `whisper-ov-v1` and `typhoon-ov-v1` and upload the 14 files of
   `~/.claude/skills/meeting-summary/models/<name>-ov/` each (file list = `$OvFiles` in install.ps1).
2. Push main, `git tag v1.1.1`, push the tag; push jump-setup (app.py synced, not committed).
3. Clean-machine install test in Windows Sandbox (needs admin: enable `Containers-DisposableClientVM`, reboot).
4. Ask the boss to re-download the ZIP and run Install.bat; get a screenshot if anything is red.

## First action to resume
Check `gh auth status`; if logged in, do step 1.
