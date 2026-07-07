@echo off
REM Windows launcher wrapper: force runtime files onto C:.
REM Keep this file ASCII-only. The main launcher contains the real logic.

setlocal enableextensions enabledelayedexpansion
cd /d "%~dp0"

set "PIANKE_RUNTIME_DIR=C:\xiaoyang-photo-picker-runtime"

for %%F in ("%~dp0*Windows.bat") do (
  if /I not "%%~nxF"=="%~nx0" (
    call "%%~fF"
    set "RC=!errorlevel!"
    endlocal & exit /b !RC!
  )
)

echo.
echo [ERROR] Main Windows launcher was not found.
echo Please keep this file next to the original Windows launcher.
pause
endlocal & exit /b 1
