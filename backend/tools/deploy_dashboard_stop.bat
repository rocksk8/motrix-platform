@echo off
rem Stops the local deploy dashboard (deploy_dashboard.py). Double-click this file.
rem NOTE: keep this file plain ASCII only (no Chinese) - see
rem feedback_windows_locale_encoding_pitfall: cmd.exe misparses multi-byte
rem UTF-8 bytes in .bat files under this machine's default codepage.

powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Write-Host 'Deploy dashboard stopped.' } else { Write-Host 'Deploy dashboard is not running.' }"

pause
