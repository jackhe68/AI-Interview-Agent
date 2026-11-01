@echo off
chcp 65001 >nul
title AI Interview Agent - Public Test
if not exist "D:\AI_Interview_Agent\tools\start_public_test.ps1" (
  echo 找不到项目启动脚本，请确认项目仍在 D:\AI_Interview_Agent。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\AI_Interview_Agent\tools\start_public_test.ps1"
if errorlevel 1 echo 启动未完成，请查看上方错误提示。
echo.
echo 网址显示后可以关闭这个窗口，后台服务仍会运行。
pause
