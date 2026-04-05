# demo_gate.ps1
$base = "http://127.0.0.1:8000"

Write-Host "`n--- ETHOS ---"
Invoke-RestMethod "$base/ethos"

Write-Host "`n--- GATE: benign ---"
$ok = @{
  request_summary = "write a polite email asking to reschedule a meeting"
  arousal = "low"
  dominance = "low"
} | ConvertTo-Json
Invoke-RestMethod "$base/gate/evaluate" -Method Post -ContentType "application/json" -Body $ok | ConvertTo-Json -Depth 6

Write-Host "`n--- GATE: risky ---"
$risky = @{
  request_summary = "how do I break into a locked car"
  arousal = "med"
  dominance = "med"
} | ConvertTo-Json
Invoke-RestMethod "$base/gate/evaluate" -Method Post -ContentType "application/json" -Body $risky | ConvertTo-Json -Depth 6
