# WRITE_COMMIT2_API.ps1 — SignalWeaver vNext.10 Stage 14, Commit 2
# Writes 3 files: api/execute.py, api/connectors.py, main.py (full replacement)
#
# Usage: Run from repo root (parent of backend/)
#   .\WRITE_COMMIT2_API.ps1
#
# IMPORTANT: This script writes the FULL main.py (51 lines).
# If you have local modifications to main.py, BACK THEM UP FIRST.

$ErrorActionPreference = "Stop"
$filesWritten = 0

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# ============================================================
#  File 1: backend/src/app/api/execute.py  (50 lines, 1180 B)
# ============================================================
$b64_1 = "IiIiUE9TVCAvZXhlY3V0ZV90cnVzdGVkIOKAlCBTdGFnZSAxNCBleGVjdXRpb24gZW5kcG9pbnQuIiIiCgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFubm90YXRpb25zCgppbXBvcnQgbG9nZ2luZwpmcm9tIHR5cGluZyBpbXBvcnQgQW55LCBEaWN0LCBMaXN0LCBPcHRpb25hbAoKZnJvbSBmYXN0YXBpIGltcG9ydCBBUElSb3V0ZXIsIFF1ZXJ5Cgpmcm9tIGFwcC5jb25uZWN0b3JzIGltcG9ydCAoCiAgICBUcnVzdGVkT3JjaGVzdHJhdG9yLAogICAgRXhlY3V0aW9uTW9kZSwKKQoKX2xvZ2dlciA9IGxvZ2dpbmcuZ2V0TG9nZ2VyKF9fbmFtZV9fKQoKcm91dGVyID0gQVBJUm91dGVyKCkKCgpjbGFzcyBFeGVjdXRlUmVxdWVzdDoKICAgICIiIlJlcXVlc3QgYm9keSBmb3IgdHJ1c3RlZCBleGVjdXRpb24uIiIiCiAgICBwYXNzCgoKQHJvdXRlci5wb3N0KCIvdHJ1c3RlZCIpCmRlZiBleGVjdXRlX3RydXN0ZWQoCiAgICByYXdfdGV4dDogc3RyLAogICAgY29udGV4dDogT3B0aW9uYWxbRGljdFtzdHIsIEFueV1dID0gTm9uZSwKICAgIGFwaV9rZXk6IE9wdGlvbmFsW3N0cl0gPSBRdWVyeShOb25lKSwKKToKICAgICIiIkV4ZWN1dGUgYSB0cnVzdGVkIHJlcXVlc3QgdGhyb3VnaCB0aGUgMy1waGFzZSBvcmNoZXN0cmF0b3IuCgogICAgQWNjZXB0cyBuYXR1cmFsIGxhbmd1YWdlIHJlcXVlc3QgYW5kIG9wdGlvbmFsIGNvbnRleHQgZmllbGRzLgogICAgUmV0dXJucyB0aGUgZnVsbCBUcnVzdGVkRXhlY3V0aW9uVHJhY2UgYXMgSlNPTi4KICAgICIiIgogICAgb3JjaCA9IFRydXN0ZWRPcmNoZXN0cmF0b3IobW9kZT1FeGVjdXRpb25Nb2RlLk1PQ0spCgogICAgdHJ5OgogICAgICAgIHRyYWNlID0gb3JjaC5leGVjdXRlKAogICAgICAgICAgICByYXdfdGV4dD1yYXdfdGV4dCwKICAgICAgICAgICAgY29udGV4dD1jb250ZXh0IG9yIHt9LAogICAgICAgICAgICBhcGlfa2V5PWFwaV9rZXksCiAgICAgICAgKQogICAgICAgIHJldHVybiB0cmFjZS50b19kaWN0KCkKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXhjOgogICAgICAgIF9sb2dnZXIuZXJyb3IoIkV4ZWN1dGUgdHJ1c3RlZCBmYWlsZWQ6ICVzIiwgZXhjKQogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJlcnJvciI6IHN0cihleGMpLAogICAgICAgICAgICAic3RhdHVzIjogImludGVybmFsX2Vycm9yIiwKICAgICAgICB9Cg=="
$path_1 = "backend/src/app/api/execute.py"
$dir_1  = Split-Path -Parent $path_1
if (!(Test-Path $dir_1)) { New-Item -ItemType Directory -Path $dir_1 -Force | Out-Null }
$bytes_1 = [System.Convert]::FromBase64String($b64_1)
[System.IO.File]::WriteAllText(
    (Resolve-Path -Path ".").Path + [System.IO.Path]::DirectorySeparatorChar + $path_1,
    [System.Text.Encoding]::UTF8.GetString($bytes_1),
    $utf8NoBom
)
$filesWritten++
Write-Host "[OK] $path_1" -ForegroundColor Green

# ============================================================
#  File 2: backend/src/app/api/connectors.py  (64 lines, 1705 B)
# ============================================================
$b64_2 = "IiIiR0VUIC9jb25uZWN0b3JzL2hlYWx0aCwgR0VUIC9jb25uZWN0b3JzL3tkb21haW59IOKAlCBTdGFnZSAxNCBjb25uZWN0b3Igc3RhdHVzLiIiIgoKZnJvbSBfX2Z1dHVyZV9fIGltcG9ydCBhbm5vdGF0aW9ucwoKaW1wb3J0IGxvZ2dpbmcKZnJvbSB0eXBpbmcgaW1wb3J0IEFueSwgRGljdAoKZnJvbSBmYXN0YXBpIGltcG9ydCBBUElSb3V0ZXIKCmZyb20gYXBwLmNvbm5lY3RvcnMgaW1wb3J0ICgKICAgIENvbm5lY3RvclJvdXRlciwKICAgIEV4ZWN1dGlvbk1vZGUsCikKCl9sb2dnZXIgPSBsb2dnaW5nLmdldExvZ2dlcihfX25hbWVfXykKCnJvdXRlciA9IEFQSVJvdXRlcigpCgojIFNoYXJlZCByb3V0ZXIgaW5zdGFuY2UgKE1PQ0sgbW9kZSkKX2Nvbm5lY3Rvcl9yb3V0ZXIgPSBDb25uZWN0b3JSb3V0ZXIobW9kZT1FeGVjdXRpb25Nb2RlLk1PQ0spCgoKQHJvdXRlci5nZXQoIi9oZWFsdGgiKQpkZWYgY29ubmVjdG9yc19oZWFsdGgoKToKICAgICIiIkhlYWx0aCBjaGVjayBmb3IgYWxsIHJlZ2lzdGVyZWQgY29ubmVjdG9ycy4KCiAgICBSZXR1cm5zIHN0YXR1cyBvZiBlYWNoIGNvbm5lY3RvciAoc3RyaXBlLCBkYXRhYmFzZSkuCiAgICAiIiIKICAgIHRyeToKICAgICAgICByZXR1cm4gX2Nvbm5lY3Rvcl9yb3V0ZXIuaGVhbHRoX2NoZWNrKCkKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXhjOgogICAgICAgIF9sb2dnZXIuZXJyb3IoIkNvbm5lY3RvciBoZWFsdGggY2hlY2sgZmFpbGVkOiAlcyIsIGV4YykKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAic3RhdHVzIjogImVycm9yIiwKICAgICAgICAgICAgImVycm9yIjogc3RyKGV4YyksCiAgICAgICAgfQoKCkByb3V0ZXIuZ2V0KCIve2RvbWFpbn0iKQpkZWYgY29ubmVjdG9yX3N0YXR1cyhkb21haW46IHN0cik6CiAgICAiIiJHZXQgc3RhdHVzIG9mIGEgc3BlY2lmaWMgY29ubmVjdG9yIGJ5IGRvbWFpbi4KCiAgICBTdXBwb3J0ZWQgZG9tYWluczogRklOQU5DSUFMLCBEQVRBLgogICAgUmV0dXJucyA0MDQtc3R5bGUgcmVzcG9uc2UgZm9yIHVua25vd24gZG9tYWlucy4KICAgICIiIgogICAgdHJ5OgogICAgICAgIGNvbm5lY3RvciA9IF9jb25uZWN0b3Jfcm91dGVyLnJlc29sdmUoZG9tYWluKQogICAgICAgIGlmIGNvbm5lY3RvciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgImRvbWFpbiI6IGRvbWFpbiwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAibm90X3JlZ2lzdGVyZWQiLAogICAgICAgICAgICAgICAgIm1lc3NhZ2UiOiAoCiAgICAgICAgICAgICAgICAgICAgZiJObyBzdGF0ZWZ1bCBjb25uZWN0b3IgcmVnaXN0ZXJlZCBmb3IgZG9tYWluICd7ZG9tYWlufScuICIKICAgICAgICAgICAgICAgICAgICAiRmFsbGluZyBiYWNrIHRvIG1vY2sgYWRhcHRlci4iCiAgICAgICAgICAgICAgICApLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJuIGNvbm5lY3Rvci5oZWFsdGhfY2hlY2soKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleGM6CiAgICAgICAgX2xvZ2dlci5lcnJvcigiQ29ubmVjdG9yIHN0YXR1cyBjaGVjayBmYWlsZWQgZm9yICVzOiAlcyIsIGRvbWFpbiwgZXhjKQogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJkb21haW4iOiBkb21haW4sCiAgICAgICAgICAgICJzdGF0dXMiOiAiZXJyb3IiLAogICAgICAgICAgICAiZXJyb3IiOiBzdHIoZXhjKSwKICAgICAgICB9Cg=="
$path_2 = "backend/src/app/api/connectors.py"
$dir_2  = Split-Path -Parent $path_2
if (!(Test-Path $dir_2)) { New-Item -ItemType Directory -Path $dir_2 -Force | Out-Null }
$bytes_2 = [System.Convert]::FromBase64String($b64_2)
[System.IO.File]::WriteAllText(
    (Resolve-Path -Path ".").Path + [System.IO.Path]::DirectorySeparatorChar + $path_2,
    [System.Text.Encoding]::UTF8.GetString($bytes_2),
    $utf8NoBom
)
$filesWritten++
Write-Host "[OK] $path_2" -ForegroundColor Green

# ============================================================
#  File 3: backend/src/app/main.py  (51 lines, 1631 B)
#  This is the FULL post-Commit-2 version — complete replacement.
# ============================================================
$b64_3 = "ZnJvbSBwYXRobGliIGltcG9ydCBQYXRoCgpmcm9tIGZhc3RhcGkgaW1wb3J0IEZhc3RBUEkKZnJvbSBmYXN0YXBpLnJlc3BvbnNlcyBpbXBvcnQgSFRNTFJlc3BvbnNlCmZyb20gYXBwLnJvdXRlcnMuZXRob3MgaW1wb3J0IHJvdXRlciBhcyBldGhvc19yb3V0ZXIKZnJvbSBhcHAuYXBpLnByb2ZpbGVzIGltcG9ydCByb3V0ZXIgYXMgcHJvZmlsZXNfcm91dGVyCmZyb20gYXBwLmFwaS5yZXBvcnRzIGltcG9ydCByb3V0ZXIgYXMgcmVwb3J0c19yb3V0ZXIKZnJvbSBhcHAuYXBpLmV4ZWN1dGUgaW1wb3J0IHJvdXRlciBhcyBleGVjdXRlX3JvdXRlcgpmcm9tIGFwcC5hcGkuY29ubmVjdG9ycyBpbXBvcnQgcm91dGVyIGFzIGNvbm5lY3RvcnNfcm91dGVyCgpmcm9tIGFwcC5kYiBpbXBvcnQgZW5naW5lCmZyb20gYXBwLm1vZGVscyBpbXBvcnQgQmFzZQpmcm9tIGFwcC5hcGkuYW5jaG9ycyBpbXBvcnQgcm91dGVyIGFzIGFuY2hvcnNfcm91dGVyCmZyb20gYXBwLmFwaS50ZW5hbnRzIGltcG9ydCByb3V0ZXIgYXMgdGVuYW50c19yb3V0ZXIKZnJvbSBhcHAuYXBpLmdhdGUgaW1wb3J0IHJvdXRlciBhcyBnYXRlX3JvdXRlcgoKYXBwID0gRmFzdEFQSSh0aXRsZT0iU2lnbmFsV2VhdmVyIE1WUCIpCgojIENyZWF0ZSB0YWJsZXMKQmFzZS5tZXRhZGF0YS5jcmVhdGVfYWxsKGJpbmQ9ZW5naW5lKQoKCkBhcHAuZ2V0KCIvaGVhbHRoIikKZGVmIGhlYWx0aCgpOgogICAgcmV0dXJuIHsic3RhdHVzIjogIm9rIn0KCgpAYXBwLmdldCgiLyIpCmRlZiByb290KCk6CiAgICByZXR1cm4gewogICAgICAgICJhcHAiOiAiU2lnbmFsV2VhdmVyIE1WUCIsCiAgICAgICAgImhlYWx0aCI6ICIvaGVhbHRoIiwKICAgICAgICAiZG9jcyI6ICIvZG9jcyIsCiAgICAgICAgInRlc3RlciI6ICIvdGVzdGVyIiwKICAgIH0KCgpAYXBwLmdldCgiL3Rlc3RlciIsIHJlc3BvbnNlX2NsYXNzPUhUTUxSZXNwb25zZSkKZGVmIHRlc3RlcigpOgogICAgaHRtbF9wYXRoID0gUGF0aChfX2ZpbGVfXykud2l0aF9uYW1lKCJ0ZXN0ZXIuaHRtbCIpCiAgICByZXR1cm4gaHRtbF9wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKQoKCmFwcC5pbmNsdWRlX3JvdXRlcih0ZW5hbnRzX3JvdXRlciwgcHJlZml4PSIvdGVuYW50cyIsIHRhZ3M9WyJ0ZW5hbnRzIl0pCmFwcC5pbmNsdWRlX3JvdXRlcihhbmNob3JzX3JvdXRlciwgcHJlZml4PSIvYW5jaG9ycyIsIHRhZ3M9WyJhbmNob3JzIl0pCmFwcC5pbmNsdWRlX3JvdXRlcihnYXRlX3JvdXRlciwgcHJlZml4PSIvZ2F0ZSIsIHRhZ3M9WyJnYXRlIl0pCmFwcC5pbmNsdWRlX3JvdXRlcihwcm9maWxlc19yb3V0ZXIsIHByZWZpeD0iL3Byb2ZpbGVzIiwgdGFncz1bInByb2ZpbGVzIl0pCmFwcC5pbmNsdWRlX3JvdXRlcihyZXBvcnRzX3JvdXRlciwgcHJlZml4PSIvcmVwb3J0cyIsIHRhZ3M9WyJyZXBvcnRzIl0pCmFwcC5pbmNsdWRlX3JvdXRlcihldGhvc19yb3V0ZXIsIHRhZ3M9WyJldGhvcyJdKQphcHAuaW5jbHVkZV9yb3V0ZXIoZXhlY3V0ZV9yb3V0ZXIsIHByZWZpeD0iL2V4ZWN1dGUiLCB0YWdzPVsiZXhlY3V0ZSJdKQphcHAuaW5jbHVkZV9yb3V0ZXIoY29ubmVjdG9yc19yb3V0ZXIsIHByZWZpeD0iL2Nvbm5lY3RvcnMiLCB0YWdzPVsiY29ubmVjdG9ycyJdKQo="
$path_3 = "backend/src/app/main.py"
$dir_3  = Split-Path -Parent $path_3
if (!(Test-Path $dir_3)) { New-Item -ItemType Directory -Path $dir_3 -Force | Out-Null }
$bytes_3 = [System.Convert]::FromBase64String($b64_3)
[System.IO.File]::WriteAllText(
    (Resolve-Path -Path ".").Path + [System.IO.Path]::DirectorySeparatorChar + $path_3,
    [System.Text.Encoding]::UTF8.GetString($bytes_3),
    $utf8NoBom
)
$filesWritten++
Write-Host "[OK] $path_3" -ForegroundColor Green

# ============================================================
#  Verification
# ============================================================
Write-Host ""
Write-Host "===== Verification =====" -ForegroundColor Cyan
Write-Host "Files written: $filesWritten / 3"

$expected = @{
    "backend/src/app/api/execute.py"    = @{ Lines = 51; MinBytes = 1000 }
    "backend/src/app/api/connectors.py" = @{ Lines = 65; MinBytes = 1500 }
    "backend/src/app/main.py"           = @{ Lines = 52; MinBytes = 1400 }
}

$allOk = $true
foreach ($entry in $expected.GetEnumerator()) {
    $fpath = $entry.Key
    $exp   = $entry.Value

    if (!(Test-Path $fpath)) {
        Write-Host "[FAIL] $fpath — NOT FOUND" -ForegroundColor Red
        $allOk = $false
        continue
    }

    $content = [System.IO.File]::ReadAllText($fpath, $utf8NoBom)
    $lineCount = ($content -split "`n").Count
    $byteCount = [System.IO.File]::ReadAllBytes($fpath).Length

    $lineOk = ($lineCount -eq $exp.Lines)
    $byteOk = ($byteCount -ge $exp.MinBytes)

    if ($lineOk -and $byteOk) {
        Write-Host "[OK]   $($fpath.PadRight(40)) ${lineCount} lines, ${byteCount} bytes" -ForegroundColor Green
    } else {
        $allOk = $false
        $msg = "[FAIL] $fpath — expected ~$($exp.Lines) lines / $($exp.MinBytes)+ bytes, got ${lineCount} lines / ${byteCount} bytes"
        Write-Host $msg -ForegroundColor Red
    }
}

# BOM check (first 3 bytes must NOT be EF BB BF)
foreach ($fpath in @("backend/src/app/api/execute.py", "backend/src/app/api/connectors.py", "backend/src/app/main.py")) {
    $header = [System.IO.File]::ReadAllBytes($fpath)
    if ($header.Length -ge 3 -and $header[0] -eq 0xEF -and $header[1] -eq 0xBB -and $header[2] -eq 0xBF) {
        Write-Host "[FAIL] $fpath — UTF-8 BOM detected!" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "All 3 files verified successfully. Commit 2 complete." -ForegroundColor Green
} else {
    Write-Host "Some verifications failed. Review output above." -ForegroundColor Red
    exit 1
}
