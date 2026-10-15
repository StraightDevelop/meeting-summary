# สรุปประชุม (Meeting Summary)

ลากไฟล์คลิปประชุมเข้าไป → ได้อีเมลสรุปสำหรับผู้บริหาร (`.eml`) พร้อมรายงานฉบับเต็มแนบมา
ถอดเสียงบนเครื่องตัวเอง (Typhoon Whisper สำหรับภาษาไทย / Whisper สำหรับภาษาอื่น) แล้วให้ Claude เขียนสรุป

## ติดตั้ง (ครั้งเดียว, Windows 10/11)

1. กดปุ่มสีเขียว **Code** ด้านบน → **Download ZIP**
2. คลิกขวาไฟล์ ZIP ที่โหลดมา → **Extract All…** (ต้องแตกไฟล์ก่อน ห้ามเปิดจากใน ZIP)
3. ในโฟลเดอร์ที่แตกออกมา ดับเบิลคลิก **Install.bat**
   - ถ้ามีหน้าต่าง "Windows protected your PC" → กด **More info** → **Run anyway**
   - ถ้ามีหน้าต่างถามสิทธิ์ (ติดตั้ง Git) → กด **Yes**
   - เบราว์เซอร์จะเปิดหน้า login Claude → login ด้วยบัญชี Claude (Pro / Max / Team) แล้วกลับมาที่หน้าต่างดำ
   - ครั้งแรกต้องดาวน์โหลดประมาณ 3–4 GB ใช้เวลา 10–30 นาทีตามความเร็วเน็ต
4. เสร็จแล้วจะมีไอคอน **สรุปประชุม** บน Desktop

ติดตั้งไม่ผ่าน/เน็ตหลุด: เปิด Install.bat ใหม่ได้เลย ส่วนที่เสร็จแล้วจะถูกข้าม

## ใช้งาน

- ดับเบิลคลิกไอคอน **สรุปประชุม** → กด **เลือกไฟล์ประชุม…** → เลือกคลิป (.mp4 .mov .mkv .webm .mp3 .m4a .wav)
- หรือลากไฟล์คลิปไปวางบนไอคอน **สรุปประชุม** ได้เลย
- รอจนทั้ง 3 ขั้นขึ้นเครื่องหมายถูก (คลิป 1 ชั่วโมง อาจใช้ 20–60 นาที ขึ้นกับเครื่อง)
- จะได้สรุป 3 ฉบับ กดฉบับไหนก็เปิดในเบราว์เซอร์ได้เลย จะก๊อปข้อความหรือเก็บไฟล์ไว้ก็ได้
  - **สรุปผู้บริหาร** อ่านจบใน 3 นาที
  - **รายงานฉบับเต็ม** ทุกหัวข้อ พร้อมภาพสไลด์
  - **ฉบับข้อความล้วน** ก๊อปไปวางใน Word หรืออีเมลได้ทันที

login Claude ครั้งเดียวตอนติดตั้ง เครื่องจะจำไว้ ปิดเครื่องแล้วเปิดใหม่ก็ไม่ต้อง login ซ้ำ มุมขวาบนของโปรแกรมจะบอกว่า login ด้วยบัญชีไหนอยู่ และมีปุ่ม **ออกจากระบบ** / **เข้าสู่ระบบ** ให้กด

ไฟล์ทั้งหมดจะอยู่โฟลเดอร์เดียวกับคลิป เสียงไม่ถูกส่งออกจากเครื่อง ส่วนข้อความที่ถอดได้จะถูกส่งให้ Claude เพื่อสรุป

---

## สำหรับผู้ดูแล

- `skill/` = Claude Code skill (`SKILL.md`, `transcribe.py`, `frames.py`, `make_email.py`, templates) + `app.py` (หน้าต่าง Tk)
- `install.ps1` ติดตั้งลง `%USERPROFILE%\.claude\skills\meeting-summary`: uv + Python 3.12 venv, โมเดล, Git, Claude Code + `claude auth login`, shortcut บน Desktop
- โมเดล: Whisper large-v3-turbo จาก [deepdml/faster-whisper-large-v3-turbo-ct2](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2); Typhoon จาก Release `models-v1` ของ repo นี้ (CTranslate2 float16 ของ [typhoon-ai/typhoon-whisper-turbo](https://huggingface.co/typhoon-ai/typhoon-whisper-turbo), MIT)
- เครื่องที่มี NVIDIA GPU ใช้ CUDA อัตโนมัติ; Intel GPU (OpenVINO) ต้องวางโมเดล `*-ov` เพิ่มเอง ไม่งั้นใช้ CPU
- อัปเดต: แก้ไฟล์ใน `skill/` → push → ผู้ใช้โหลด ZIP ใหม่แล้วเปิด Install.bat (โมเดลไม่โหลดซ้ำ)
