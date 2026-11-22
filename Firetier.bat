@echo off
setlocal
rem Firetier: starts the local UI server (127.0.0.1 only) and opens it in an Edge app window.
rem "Firetier.bat classic" opens the older Tk window instead.
set "APP=%~dp0server.py"
if /i "%~1"=="classic" set "APP=%~dp0firetier.py"
if exist "%~dp0runtime\pythonw.exe" (
    set "TCL_LIBRARY=%~dp0runtime\tcl\tcl8.6"
    set "TK_LIBRARY=%~dp0runtime\tcl\tk8.6"
    start "" "%~dp0runtime\pythonw.exe" "%APP%"
    exit /b
)
where pythonw.exe >nul 2>&1
if errorlevel 1 (
    echo Firetier requires Python 3.10+. Use the portable build or install Python.
    pause
    exit /b 1
)
start "" pythonw.exe "%APP%"
