@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo.
echo Starting Lead QA Automation...
echo Share this with your colleague on the same network:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set "ip=%%a"
    set "ip=!ip: =!"
    echo   http://!ip!:8501
    goto :found
)
:found
echo.
echo If that address doesn't work, run "ipconfig" and use your IPv4 Address instead.
echo.
python -m streamlit run Summary.py --server.address 0.0.0.0 --server.port 8501
