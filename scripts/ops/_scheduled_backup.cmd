@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_postgres.ps1" -DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres -AlertOnSuccess -EnableOneDriveMirror
endlocal

