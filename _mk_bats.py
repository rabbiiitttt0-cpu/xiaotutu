# -*- coding: utf-8 -*-
# 生成 GBK 编码的启动/停止 bat（cmd 需要 ANSI 才能正确解析中文）
NUL = "nu" + "l"  # 防 MSYS 参数转换

start = """@echo off
title 看图兔-启动器
cd /d %~dp0

echo ==========================================
echo   看图兔 本地一键启动
echo   后端 7780 / PC前端 5173 / 移动前端 5174
echo ==========================================
echo.

netstat -ano | findstr ":7780 " | findstr LISTENING >{N} 2>&1
if not errorlevel 1 (
    echo [提示] 后端 7780 已在运行，跳过重复启动
    goto open
)

echo [1/3] 启动后端 FastAPI :7780 ...
start "看图兔-后端" /min cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --host 127.0.0.1 --port 7780"

echo [2/3] 启动 PC 前端 :5173 ...
start "看图兔-PC前端" /min cmd /k "cd /d %~dp0frontend-pc && npm run dev"

echo [3/3] 启动移动前端 :5174 ...
start "看图兔-移动前端" /min cmd /k "cd /d %~dp0frontend-mobile && npm run dev"

echo.
echo 等待服务就绪...
set /a n=0
:wait
set /a n+=1
if %n% gtr 90 goto timeout
curl -s -o {N} http://127.0.0.1:7780/api/health 2>{N}
if errorlevel 1 (ping -n 2 127.0.0.1 >{N} & goto wait)
netstat -ano | findstr ":5173 " | findstr LISTENING >{N} 2>&1
if errorlevel 1 (ping -n 2 127.0.0.1 >{N} & goto wait)
netstat -ano | findstr ":5174 " | findstr LISTENING >{N} 2>&1
if errorlevel 1 (ping -n 2 127.0.0.1 >{N} & goto wait)

echo.
echo ==========================================
echo   全部就绪！
echo   PC 端:   http://localhost:5173
echo   移动端:  http://localhost:5174
echo   后端API: http://localhost:7780/api
echo   关闭服务：双击 停止看图兔.bat
echo ==========================================
goto open

:timeout
echo [警告] 等待超时，请查看最小化的服务窗口里的报错
if /i "%1"=="--no-open" exit /b 1
pause
exit /b 1

:open
if /i "%1"=="--no-open" exit /b 0
start http://localhost:5173
exit /b 0
""".replace("{N}", NUL)

stop = """@echo off
title 看图兔-停止
echo ==========================================
echo   看图兔 本地一键停止
echo ==========================================
echo.

for %%P in (7780 5173 5174) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
        taskkill /F /PID %%a >{N} 2>&1
    )
)

taskkill /F /FI "WINDOWTITLE eq 看图兔-后端*" >{N} 2>&1
taskkill /F /FI "WINDOWTITLE eq 看图兔-PC前端*" >{N} 2>&1
taskkill /F /FI "WINDOWTITLE eq 看图兔-移动前端*" >{N} 2>&1

ping -n 2 127.0.0.1 >{N}

netstat -ano | findstr ":7780 :5173 :5174 " | findstr LISTENING >{N} 2>&1
if errorlevel 1 (
    echo 已全部停止。
) else (
    echo [警告] 仍有端口被占用，请手动检查：
    netstat -ano | findstr ":7780 :5173 :5174 " | findstr LISTENING
)
echo.
ping -n 3 127.0.0.1 >{N}
exit /b 0
""".replace("{N}", NUL)

for name, content in [("启动看图兔.bat", start), ("停止看图兔.bat", stop),
                      ("_xt_start.bat", start), ("_xt_stop.bat", stop)]:
    with open(name, "w", encoding="gbk", newline="\r\n") as f:
        f.write(content)
print("4 files written in GBK, NUL token =", NUL)
