@echo off
setlocal
cd /d "%~dp0"
echo ***** MoneyPrinterTurbo Desktop *****
echo.
echo Starting Electron app...
echo The Streamlit backend will start automatically.
echo.

rem Ensure npm dependencies are installed
if not exist "node_modules\" (
    echo Installing npm dependencies...
    call npm install
    if errorlevel 1 (
        echo ***** Failed to install npm dependencies *****
        pause
        exit /b 1
    )
)

call npm start
pause
