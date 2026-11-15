@echo off
rem Abre la ventana de instalacion del companion (no hace falta escribir comandos).
start "" powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\ventana_instalar.ps1"
