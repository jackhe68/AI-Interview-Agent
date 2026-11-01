@echo off
chcp 65001 >nul
title AI Interview Agent - Redeploy
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\AI_Interview_Agent\tools\redeploy_public_test.ps1"
echo.
pause
