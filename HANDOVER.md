# Handover — 2026-10-16

Branch `main`. Repo: https://github.com/StraightDevelop/meeting-summary (public)
Latest release `v1.3.0`. OpenVINO models are on releases `whisper-ov-v1` and `typhoon-ov-v1`.

## Done
- **v1.3.0 (boss's request):** files are queued, not run — "+ เพิ่มไฟล์" appends (also drop on the shortcut),
  ✕ removes, natural-order numbering; work starts only on "เริ่มสรุป (N ไฟล์)". A failed run keeps the list.
- **Time estimate** under the list: `ใช้เวลาประมาณ X–Y นาที · เสร็จราว HH:MM–HH:MM น.`
  = media length (ffprobe) / speed + 30 s per file + Claude 5–15 min. Speed guessed from GPU (CPU 2x, Intel 8x,
  NVIDIA 15x) until a run measures it; `speed.json` in the install dir keeps the transcribe-step speed
  (model load excluded) and Claude minutes. Files with an existing transcript count as Claude-only.
- Hardening found by the end-to-end driver: Thai path in ffprobe stderr (cp874 decode crash), Pill canvases
  widening the window, long names (pixel-measured middle cut), >6 files (rows capped), unreadable file
  (red "เปิดไม่ได้", start blocked; ffprobe missing never blocks), stale results on a new meeting,
  footer below the taskbar after results (window lifted to the work area; likely present in v1.2 too).
- Tested on this machine (Intel GPU): installer over existing install; e2e driver (scratchpad `e2e.py`,
  not in repo) drives the installed app: broken/duplicate/remove/8 files/long name/2-part + single real runs.
  Estimate 4–7 min vs actual 5.3 min after calibration.

## Next steps
1. Ask the boss to re-download the ZIP and run Install.bat; first estimate is the GPU guess, then calibrated.
2. Not covered: a real hour-long meeting (estimate accuracy), Claude login on a clean machine, Intel GPU on
   another laptop, a 1080p screen (lift logic tested on a 1200-px work area only).

## Known gaps
- Dropping files onto the open window is not supported (Tk has no native drag-and-drop); use the button or the shortcut.
- All queued files are treated as one meeting.
- A Windows user name with Thai characters (non-ASCII %USERPROFILE%) is untested.

## First action to resume
`gh run list -R StraightDevelop/meeting-summary` (gh is not logged in; GH_TOKEN from `git credential fill` works).
