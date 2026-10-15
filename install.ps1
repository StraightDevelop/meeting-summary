# One-click setup for the meeting-summary skill (Windows). Safe to re-run: finished parts are skipped.
param([string]$Dest = "$env:USERPROFILE\.claude\skills\meeting-summary")
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$Files = 'config.json', 'model.bin', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json'
$Models = @{
    'whisper-large-v3-turbo' = 'https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/resolve/main'
    'typhoon-whisper-turbo'  = 'https://github.com/StraightDevelop/meeting-summary/releases/download/models-v1'
}
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"

function Step($n, $msg) { Write-Host "`n[$n/6] $msg" -ForegroundColor Cyan }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Check($what) { if ($LASTEXITCODE) { throw "$what (exit $LASTEXITCODE)" } }

try {
    Step 1 'คัดลอกโปรแกรม'
    New-Item -ItemType Directory -Force $Dest | Out-Null
    Copy-Item "$PSScriptRoot\skill\*" $Dest -Recurse -Force

    Step 2 'ติดตั้ง Python และไลบรารี (ครั้งแรกใช้เวลาหลายนาที)'
    if (-not (Have uv)) { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
    uv venv --allow-existing --python 3.12 "$Dest\.venv"; Check 'uv venv'
    uv pip install --python "$Dest\.venv\Scripts\python.exe" -r "$Dest\requirements.txt"; Check 'pip install'

    Step 3 'ดาวน์โหลดโมเดลถอดเสียง (~3.2 GB, หลุดแล้วเปิดใหม่จะต่อจากเดิม)'
    foreach ($name in $Models.Keys) {
        $dir = "$Dest\models\$name"
        New-Item -ItemType Directory -Force $dir | Out-Null
        foreach ($f in $Files) {
            if (Test-Path "$dir\$f") { continue }
            Write-Host "  $name/$f"
            curl.exe -L --fail --retry 5 -C - -o "$dir\$f.part" "$($Models[$name])/$f"; Check "download $f"
            Move-Item "$dir\$f.part" "$dir\$f"
        }
    }

    Step 4 'ติดตั้ง Git (Claude Code ต้องใช้)'
    if (-not (Have git)) {
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements; Check 'winget git'
    }

    Step 5 'ติดตั้งและ login Claude'
    if (-not (Have claude)) { Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression }
    $loggedIn = $false
    try { $loggedIn = ((claude auth status) -join "`n" | ConvertFrom-Json).loggedIn } catch {}
    if (-not $loggedIn) {
        Write-Host '  เบราว์เซอร์จะเปิดหน้า login ของ Claude ให้ login ด้วยบัญชี Claude ของคุณ แล้วกลับมาที่หน้าต่างนี้' -ForegroundColor Yellow
        claude auth login; Check 'claude login'
    }

    Step 6 'สร้างไอคอน "สรุปประชุม" บน Desktop'
    $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'สรุปประชุม.lnk'))
    $lnk.TargetPath = "$Dest\.venv\Scripts\pythonw.exe"
    $lnk.Arguments = "`"$Dest\app.py`""
    $lnk.WorkingDirectory = $Dest
    $lnk.IconLocation = "$Dest\icon.ico,0"
    $lnk.Save()

    Write-Host "`nติดตั้งเสร็จแล้ว ดับเบิลคลิกไอคอน 'สรุปประชุม' บน Desktop เพื่อเริ่มใช้งาน" -ForegroundColor Green
}
catch {
    Write-Host "`nติดตั้งไม่สำเร็จ: $_" -ForegroundColor Red
    Write-Host 'ลองเปิด Install.bat ใหม่อีกครั้ง (ส่วนที่เสร็จแล้วจะถูกข้าม) ถ้ายังไม่ได้ ให้ถ่ายรูปหน้าจอนี้ส่งให้ผู้ดูแล'
}
