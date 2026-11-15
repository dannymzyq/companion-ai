@echo off
rem Abre la ventana para desinstalar el companion.
start "" powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\ventana_desinstalar.ps1"
