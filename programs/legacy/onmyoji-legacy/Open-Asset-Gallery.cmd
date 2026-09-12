@echo off
start "Onmyoji Asset Gallery" /min pwsh -NoProfile -File "%~dp0tools\serve-gallery.ps1" -Port 18765
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:18765/gallery/index.html"
