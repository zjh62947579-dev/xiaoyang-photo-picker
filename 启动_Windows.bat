@echo off
REM Pianke launcher for Windows.
REM
REM IMPORTANT: this file is intentionally ASCII-only. Chinese Windows cmd.exe
REM reads .bat files using the OEM code page (usually GBK/936), and UTF-8
REM multibyte sequences get mis-parsed, breaking long lines into fragments.
REM All Chinese user-facing strings live in scripts/launcher.py instead,
REM which Python handles correctly regardless of console code page.
REM
REM First double-click may show "Windows protected your PC":
REM   click "More info" -> "Run anyway". Won't show again.

setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul 2>&1

cd /d "%~dp0"

echo.
echo ============================================================
echo   Pianke launcher
echo ============================================================

REM ---- 1. prefer an existing Python 3.11 ----
set "PY311="
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY311=py -3.11"

if not defined PY311 (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY311=python"
)
if not defined PY311 (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY311="%LOCALAPPDATA%\Programs\Python\Python311\python.exe""
)
if not defined PY311 (
  if exist "%ProgramFiles%\Python311\python.exe" set "PY311="%ProgramFiles%\Python311\python.exe""
)

if defined PY311 (
  echo.
  echo Found Python 3.11, starting launcher directly...
  !PY311! scripts\launcher.py
  set "RC=!errorlevel!"
  goto :finish
)

REM ---- 2. find or install uv ----
set "UV="
where uv >nul 2>&1 && set "UV=uv"

if not defined UV (
  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
if not defined UV (
  if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
)

if not defined UV (
  echo.
  echo [first-run setup] Python 3.11 was not found.
  echo Trying to download uv ^(Python toolchain, ~30MB^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 (
    echo.
    echo [WARN] uv install failed. Network to astral.sh/GitHub may be blocked.
    echo        Trying winget to install Python 3.11 instead...
    where winget >nul 2>&1
    if not errorlevel 1 (
      winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
      py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
      if not errorlevel 1 set "PY311=py -3.11"
      if not defined PY311 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY311=python"
      )
      if defined PY311 (
        echo.
        echo Python 3.11 installed, starting launcher...
        !PY311! scripts\launcher.py
        set "RC=!errorlevel!"
        goto :finish
      )
    )
    echo.
    echo [WARN] winget did not finish Python installation.
    echo        Trying direct per-user Python 3.11 installer from python.org...
    set "PY_INSTALLER=%TEMP%\python-3.11.9-amd64.exe"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $out=Join-Path $env:TEMP 'python-3.11.9-amd64.exe'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile $out"
    if not errorlevel 1 (
      start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 Include_launcher=1 Include_pip=1 PrependPath=1 TargetDir="%LOCALAPPDATA%\Programs\Python\Python311"
      if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY311="%LOCALAPPDATA%\Programs\Python\Python311\python.exe""
      if not defined PY311 (
        py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY311=py -3.11"
      )
      if defined PY311 (
        echo.
        echo Python 3.11 installed, starting launcher...
        !PY311! scripts\launcher.py
        set "RC=!errorlevel!"
        goto :finish
      )
    )
    echo.
    echo [ERROR] Could not prepare Python automatically.
    echo         Please install Python 3.11 manually from one of these sources:
    echo         1. Microsoft Store: search "Python 3.11"
    echo         2. Python.org: https://www.python.org/downloads/release/python-3119/
    echo.
    echo         After installing Python 3.11, double-click this file again.
    set "RC=1"
    goto :finish
  )
  REM re-probe after install
  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
  if not defined UV (
    if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
  )
  echo   [OK] uv installed
)

if not defined UV (
  echo.
  echo [ERROR] uv installed but executable not found.
  echo         Close this window and double-click the launcher again.
  set "RC=1"
  goto :finish
)

set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

REM ---- 3. run launcher.py via uv (uv will fetch Python 3.11 if needed) ----
echo.
echo Preparing Python environment via uv...
"%UV%" run --no-project --python "3.11" -- python scripts\launcher.py
set "RC=%errorlevel%"

:finish
if not "%RC%"=="0" (
  echo.
  echo [launcher exited with code %RC%]
  pause
)
endlocal & exit /b %RC%
