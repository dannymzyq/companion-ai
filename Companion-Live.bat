@echo off
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0iniciar-rust.ps1" %*
