@echo off
title 看图兔-停止
echo ==========================================
echo   看图兔 本地一键停止
echo ==========================================
echo.

for %%P in (7780 5173 5174) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

taskkill /F /FI "WINDOWTITLE eq 看图兔-后端*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq 看图兔-PC前端*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq 看图兔-移动前端*" >nul 2>&1

ping -n 2 127.0.0.1 >nul

netstat -ano | findstr ":7780 :5173 :5174 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo 已全部停止。
) else (
    echo [警告] 仍有端口被占用，请手动检查：
    netstat -ano | findstr ":7780 :5173 :5174 " | findstr LISTENING
)
echo.
ping -n 3 127.0.0.1 >nul
exit /b 0
