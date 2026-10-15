# Handover — 2026-10-15

Branch `main` · last pushed commit `1ea06eb` (installer + window app). Repo: https://github.com/StraightDevelop/meeting-summary (public)

## Goal
Boss (Windows, non-technical) downloads ZIP → double-clicks `Install.bat` → logs in to Claude once → uses the desktop icon "สรุปประชุม" to turn a meeting recording into an executive `.eml`.

## Done
- `install.ps1` + `Install.bat`: uv/Python 3.12 venv, models, Git (winget), Claude Code + `claude auth login`, desktop shortcut. Re-runnable (skips finished parts). UTF-8 BOM required (PS 5.1 + Thai text).
- `skill/app.py`: Tk window; transcribe.py + frames.py locally, then `claude -p … --output-format stream-json --permission-mode acceptEdits`; opens Explorer with the .eml selected. Dropping a file onto the shortcut also works (argv).
- Models: Whisper from HF `deepdml/faster-whisper-large-v3-turbo-ct2` (same bytes as the local copy); Typhoon CT2 fp16 uploaded as Release `models-v1` (public download verified, 1,617,884,929 bytes).
- Verified on this machine: installer end to end (models already present), fresh venv from requirements.txt (`--selftest` + imports OK), app flow on a test clip → `_executive.eml` + 3 HTMLs produced, success dialog reached.
  (Harness print crashed on `→` in cp874 console — harness only, not the app.)

- 2026-10-15: window checked by screenshot; fixed clipped subtitle + DPI blur. Email now `เรียน ทุกท่าน`, no sign-off (boss sends to team/board; Outlook signature closes it). jump-setup copy synced (`7286b24`).

## Not verified yet
- Clean-machine install: real model downloads, winget Git, Claude Code install + browser login, SmartScreen prompts.
- CPU-only speed on the boss's laptop (no Intel OV models shipped → CPU fallback unless NVIDIA).

## Next steps
1. Test on a clean Windows machine/VM or a second user account: download ZIP → Install.bat → run a short clip.
2. Send the boss the ZIP link: https://github.com/StraightDevelop/meeting-summary/archive/refs/heads/main.zip
3. Optional: shortcut icon; ship `*-ov` models for Intel GPU speed (3.2 GB more).

## First action to resume
Create a second Windows user (or VM), download the ZIP there, run Install.bat.
