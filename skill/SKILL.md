---
name: meeting-summary
description: Transcribe any meeting recording locally (Typhoon Whisper for Thai, Whisper large-v3-turbo for English/other), capture key slides from video, and produce a <3-minute executive email (.eml draft) with two full versions attached — a clean-UI browser report and a plain no-UI copy for reuse — for any meeting type (budget/finance, project status, strategy, sales/customer, people/HR, team sync, training). Use WHENEVER the user gives, pastes, or drags in a path to an audio/video file (.mp4 .mov .mkv .webm .mp3 .m4a .wav), even with no other text, or says "summarize this meeting" / "สรุปประชุม". Do not ask questions first; just run it.
---

# Meeting Summary

Run the full flow without asking the user anything. The user forwards the result to their boss (a board member who cares about numbers / P&L), so the deliverable is an email, not a chat answer. Works for **any** meeting type: the files and design stay the same; only the section plan changes (step 3).

Deliverables, all next to the recording:
| File | What | Built from |
|---|---|---|
| `<stem>_executive.eml` | **what the user sends**: executive email body + both full versions attached | make_email.py |
| `<stem>_executive.html` | email body, Outlook-safe, < 3 min read | `email_template.html` |
| `<stem>_detailed.html` | full report, clean UI, opened in a browser, images inlined (one file) | `report_template.html` |
| `<stem>_plain.html` | **same full content, no UI** — plain headings/bullets/tables, easy for the boss to copy into Word/email and reuse | `email_template.html` styles |

## 1. Transcribe + capture slides (in parallel)

Strip surrounding quotes from the path. Start BOTH with the **PowerShell** tool, `run_in_background: true`:

```powershell
& "$HOME\.claude\skills\meeting-summary\.venv\Scripts\python.exe" "$HOME\.claude\skills\meeting-summary\transcribe.py" "<FULL PATH>"
& "$HOME\.claude\skills\meeting-summary\.venv\Scripts\python.exe" "$HOME\.claude\skills\meeting-summary\frames.py" "<FULL PATH>"
```

Both print progress lines like `[4/4] Transcribe ████████░░░░  58%  01:45:12 / 03:01:07  elapsed 00:11:02  ETA ~00:08:01`.
**Tell the user which step is running and the % / ETA**: read the tail of each background output file right after starting, and relay new progress every few minutes until done (use Monitor if available). frames.py takes ~1 min for 3 h of video; audio-only files print "No video track" and skip.

transcribe.py flags, only if the user asked: `--lang th|en` (default auto), `--speakers` (not installed; warns), `--force` (re-transcribe; otherwise an existing `<stem>_transcript.txt` is reused). frames.py: `--force` re-extracts, `--threshold` (default 0.01).

Relay the transcript's `Model`, `Language`, and `Processing time` lines.

## 2. Read

- `<stem>_transcript.txt`. Long or noisy transcripts repeat hallucinated tokens; collapse runs of repeated words before reading if the file is >256 KB.
- `<stem>_frames/sheet_NNN.jpg`: 4x4 contact sheets of every captured frame; `index.txt` maps `HH:MM:SS  file  sheet rXcY`. Scan all sheets, then open the full-size frames of the slides that carry the meeting's substance (numbers, timelines, decisions, org charts, risks, summaries). Skip title/agenda/thank-you slides, videos, and frames that only show participants. Consecutive frames are often the same slide; pick one.
- No video / no slides (audio only, camera-only call): skip images entirely; both templates still work without them.
- **Numbers on slides beat numbers heard in audio.** Use slides to fix units/figures the audio garbled; flag contradictions inside the deck as open questions.

## 3. Write the three HTMLs

Thai unless the user asks otherwise; keep business terms in English. First decide the **meeting type** from the transcript/slides, then use its section plan below for the detailed report and distill the executive email from it. Mixed meetings: combine plans; skip sections with nothing in them — never pad.

| Type | Detailed report sections (after 01 บทสรุปผู้บริหาร) | Hero stamp (status pill) | KPI cards / visuals |
|---|---|---|---|
| Budget / financial review | P&L per entity · why profit moves (bridge) · growth drivers · people & productivity · cash & working capital · one per subsidiary · market risks | อนุมัติแล้ว / ยังไม่อนุมัติ / อนุมัติแบบมีเงื่อนไข | sales, profit, margin, cash; growth bars (revenue vs cost growth); GP bridge |
| Project / program status | progress vs plan (milestones table) · budget used vs plan · blockers & dependencies · decisions needed · next milestones | ตามแผน / ล่าช้า / มีความเสี่ยง | % complete, days late, budget burn; growth bars = progress per workstream |
| Strategy / planning / workshop | context & problem · options considered (cards) · chosen direction & rationale · targets & KPIs · roadmap · risks | ได้ข้อสรุป / ยังไม่ได้ข้อสรุป | target numbers; cards per option/pillar |
| Sales / customer / partner | account or pipeline status · customer asks & feedback · commercial terms (price, volume, terms) · competitor notes · follow-ups | ปิดดีลได้ / กำลังเจรจา / ต้องติดตาม | volume, value, margin, win rate; mix bar per customer/product |
| People / HR / org | headcount & cost · org changes · hiring plan · performance & productivity · succession | อนุมัติ / รอพิจารณา | headcount, cost/head, revenue/head |
| Team sync / operations / general | topic-by-topic summary (one section per agenda item) · issues & resolutions · decisions | – (omit stamp) | only if the meeting quoted numbers |
| Training / briefing / town hall | key messages · what changes for us · Q&A highlights | – (omit stamp) | usually none |

Always end the detailed report with **Action items** (owner chips, due dates; unknown → `–`) and **Open questions**; include **Risks** whenever any were raised. Every number in KPI cards/bars must come from a slide or a clearly heard statement.

### 3a. `<stem>_executive.html` — the email body, readable in under 3 minutes
**Copy `email_template.html`** and fill it. Outlook-safe (inline styles + tables only — Outlook strips modern CSS). Title prefix `[Executive Summary]`, max 720px, ~one screen, greeting `เรียน [ชื่อหัวหน้า]` + sign-off `[ชื่อคุณ]`:
1. **Bottom line** box: verdict/decision/status + the one number or fact that matters, 2–3 lines
2. **Key facts table**, 4–6 rows — numbers with growth (red when worse) or, for non-numeric meetings, หัวข้อ | สถานะ
3. **3 ประเด็นที่ควรทราบ** — bold headline + 2–3 short sub-bullets each
4. **ด้านบวก** (optional) and **ขั้นตอนต่อไป** (max 3)
5. At most 1 slide image, then the line pointing to the attached `<stem>_detailed.html`

### 3b. `<stem>_detailed.html` — full report, clean UI, opened in a browser
**Copy `report_template.html`** (same folder as this file): keep its `<head>`/CSS, lightbox dialog and script untouched; fill the hero (kicker = "Board Briefing · <meeting type>", headline, one-sentence dek, meta pills, optional status stamp), the TOC (one `<li>` per section) and the sections using the component kit in its comment; delete the kit comment. No greeting / sign-off.
Design language (approved by the user 2026-10-09 — do not drift): light-grey page, one white rounded panel, centered hero with faint concentric rings, Poppins (Latin) + Prompt (Thai), monochrome black/white/grey, floating soft-shadow cards with uppercase letter-spaced labels, black pill buttons/active states, green/red reserved for better/worse numbers only.

Slides: put the chosen frames under the bullet they support, 8–15 images max. First crop meeting-app chrome (Teams sidebar/toolbar) so only the slide shows, and so participants' faces aren't in the email:

```bash
mkdir -p "<stem>_frames/email" && ffmpeg -v error -y -i "<stem>_frames/HH-MM-SS.jpg" -vf "crop=W:H:X:Y" -q:v 3 "<stem>_frames/email/HH-MM-SS.jpg"
```
(ffmpeg = `.venv\Scripts\static_ffmpeg.exe`; Teams 1280x720 frame → `crop=1108:628:6:62`; check one crop visually.)
In the report use the template's `<figure>` slide component (click to zoom), src `<stem URL-encoded>_frames/email/HH-MM-SS.jpg`, caption `ภาพ NN · what · หน้า X · HH:MM:SS`. Pair related slides two per row (`.shots`), a single key slide full width (`.shots one`).

Rules: names, numbers, amounts, dates, company/product terms exactly as on the slide or as spoken; garbled/unsure → `[ไม่ชัด]`; never invent decisions or action items; end with a source note.

### 3c. `<stem>_plain.html` — same full content, no UI
Write it right after 3b with **identical content and section order** (same numbers, bullets, tables, action items, open questions, slides), but in the plain email-safe style of `email_template.html`: inline styles only, `<h2>` title + one context line, numbered `<h3>` section headers (blue underline), bullets with nested sub-bullets, `<table border=1 cellpadding=6>` tables, slides as `<img width="680" style="width:100%;max-width:680px">` + a `ภาพ N: what (สไลด์หน้า X · นาทีที่ HH:MM:SS)` caption. No KPI cards, bars, stamps, TOC, scripts or web fonts. No greeting / sign-off. Title prefix `[ฉบับธรรมดา]`.

## 4. Package, check, open

```powershell
$py = "$HOME\.claude\skills\meeting-summary\.venv\Scripts\python.exe"; $me = "$HOME\.claude\skills\meeting-summary\make_email.py"
& $py $me --standalone "<stem>_detailed.html"                        # inline slides as data: URIs -> one self-contained file
& $py $me --standalone "<stem>_plain.html"
& $py $me "<stem>_executive.html" --attach "<stem>_detailed.html" --attach "<stem>_plain.html"   # -> <stem>_executive.eml
```
Before `--standalone`, screenshot the HTMLs with headless Edge (`Start-Process -Wait msedge --headless=new --virtual-time-budget=5000 --window-size=1366,2400 --screenshot=...`; also ~520px wide for mobile — headless can't go narrower) and look at them; the executive one must fit roughly one screen. Then open the HTMLs for the user (`Start-Process`).

## 5. Reply

Briefly: model / language / processing time, frames captured, paths of the .eml (what to send) and the three .html files, how to send (double-click .eml → add recipient → send; both full versions travel as attachments), and the executive bottom line.
