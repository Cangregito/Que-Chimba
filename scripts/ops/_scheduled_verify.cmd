@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_restore_postgres.ps1" -DbHost localhost -DbPort 5432 -DbUser postgres -AlertOnSuccess
endlocal

