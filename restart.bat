@echo off
echo [restart] 停止现有 Streamlit 进程...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8501 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [restart] 启动 Streamlit...
start /b "" cmd /c "cd /d %~dp0 && streamlit run app.py > streamlit.log 2>&1"

timeout /t 3 /nobreak >nul
echo [restart] 服务已重启，访问 http://localhost:8501
