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
set "RC=1"

cd /d "%~dp0"

set "PROJECT_DRIVE=%CD:~0,2%"
set "LAUNCHER_BASE=%PROJECT_DRIVE%\xiaoyang-photo-picker-runtime"
if /I "%PROJECT_DRIVE%"=="C:" (
  if exist "D:\" set "LAUNCHER_BASE=D:\xiaoyang-photo-picker-runtime"
  if not exist "D:\" (
    if exist "E:\" set "LAUNCHER_BASE=E:\xiaoyang-photo-picker-runtime"
  )
)
if defined PIANKE_RUNTIME_DIR set "LAUNCHER_BASE=%PIANKE_RUNTIME_DIR%"
set "LAUNCHER_CACHE=%LAUNCHER_BASE%\.launcher-cache"
set "LAUNCHER_PYTHON_DIR=%LAUNCHER_BASE%\.launcher-python\Python311"
set "PIANKE_RUNTIME_DIR=%LAUNCHER_BASE%"
set "UV_CACHE_DIR=%LAUNCHER_BASE%\.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%LAUNCHER_BASE%\.uv-python"
set "PIP_CACHE_DIR=%LAUNCHER_BASE%\.pip-cache"

echo.
echo ============================================================
echo   Pianke launcher
echo ============================================================
echo Runtime directory: %LAUNCHER_BASE%

REM ---- 1. prefer an existing Python 3.11 ----
set "PY311_EXE="
set "PY311_ARGS="
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PY311_EXE=py"
  set "PY311_ARGS=-3.11"
)

if not defined PY311_EXE (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY311_EXE=python"
)
if not defined PY311_EXE (
  if exist "%LAUNCHER_PYTHON_DIR%\python.exe" set "PY311_EXE=%LAUNCHER_PYTHON_DIR%\python.exe"
)
if not defined PY311_EXE (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY311_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PY311_EXE (
  if exist "%ProgramFiles%\Python311\python.exe" set "PY311_EXE=%ProgramFiles%\Python311\python.exe"
)

if defined PY311_EXE (
  echo.
  echo Found Python 3.11, starting launcher directly...
  "!PY311_EXE!" !PY311_ARGS! scripts\launcher.py
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
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' | Invoke-Expression"
  if errorlevel 1 (
    echo.
    echo [WARN] uv install failed. Network to astral.sh/GitHub may be blocked.
    echo        Trying winget to install Python 3.11 instead...
    where winget >nul 2>&1
    if not errorlevel 1 (
      winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
      py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
      if not errorlevel 1 (
        set "PY311_EXE=py"
        set "PY311_ARGS=-3.11"
      )
      if not defined PY311_EXE (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY311_EXE=python"
      )
      if defined PY311_EXE (
        echo.
        echo Python 3.11 installed, starting launcher...
        "!PY311_EXE!" !PY311_ARGS! scripts\launcher.py
        set "RC=!errorlevel!"
        goto :finish
      )
    )
    echo.
    echo [WARN] winget did not finish Python installation.
    echo        Trying direct per-user Python 3.11 installer from python.org...
    set "PY_INSTALLER_ARCH=amd64"
    set "PY_INSTALLER_NAME=python-3.11.9-amd64.exe"
    if /I "%PROCESSOR_ARCHITECTURE%"=="x86" (
      if "%PROCESSOR_ARCHITEW6432%"=="" (
        set "PY_INSTALLER_ARCH=win32"
        set "PY_INSTALLER_NAME=python-3.11.9.exe"
      )
    )
    mkdir "%LAUNCHER_CACHE%" >nul 2>&1
    set "PY_INSTALLER=%LAUNCHER_CACHE%\!PY_INSTALLER_NAME!"
    set "PY_INSTALLER_URL=https://www.python.org/ftp/python/3.11.9/!PY_INSTALLER_NAME!"
    echo        Downloading !PY_INSTALLER_NAME! to !PY_INSTALLER!
    echo        Please wait. Do not close this window while the download is running.
    if exist "!PY_INSTALLER!" del /f /q "!PY_INSTALLER!" >nul 2>&1
    certutil -urlcache -split -f "!PY_INSTALLER_URL!" "!PY_INSTALLER!"
    if errorlevel 1 (
      echo        certutil download failed, trying PowerShell fallback...
      powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:PY_INSTALLER_URL -OutFile $env:PY_INSTALLER"
    )
    if not errorlevel 1 (
      start /wait "" "!PY_INSTALLER!" /quiet InstallAllUsers=0 Include_launcher=1 Include_pip=1 PrependPath=1 TargetDir="%LAUNCHER_PYTHON_DIR%"
      if exist "%LAUNCHER_PYTHON_DIR%\python.exe" set "PY311_EXE=%LAUNCHER_PYTHON_DIR%\python.exe"
      if not defined PY311_EXE (
        py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 (
          set "PY311_EXE=py"
          set "PY311_ARGS=-3.11"
        )
      )
      if defined PY311_EXE (
        echo.
        echo Python 3.11 installed, starting launcher...
        "!PY311_EXE!" !PY311_ARGS! scripts\launcher.py
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
echo.
echo [launcher exited with code %RC%]
if not "%PIANKE_NO_PAUSE%"=="1" (
  echo.
  pause
)
endlocal & exit /b %RC%
