@echo off
setlocal
cd /d "%~dp0"
title MiniWar AFK Bot - Setup

echo.
echo ========================================
echo   MiniWar AFK Bot - Setup
echo ========================================
echo.

echo [1/3] Unblocking files...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%CD%' -Recurse -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue"
echo       Done.
echo.

echo [2/3] Checking .NET 8 Desktop + WebView2...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$true; $k='HKLM:\SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App'; if(Test-Path $k){$v=Get-ChildItem $k|Where-Object{$_.PSChildName -like '8.*'}}; if(-not $v){$ok=$false}} else {$ok=$false}; if(-not (Test-Path 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')){$ok=$false}; if($ok){exit 0} else {exit 1}"
if %errorlevel%==0 (
  echo       Already installed - skipping winget.
  goto launch
)

where winget >nul 2>&1
if not %errorlevel%==0 (
  echo       winget not found - skipping auto-install.
  echo       If the bot fails, install .NET 8 Desktop x64 + WebView2 manually.
  goto launch
)

echo       Missing runtimes - installing via winget...
echo       THIS CAN TAKE 3-10 MINUTES. Do not close this window.
echo       If a UAC prompt appears, click Yes.
echo.
echo       Installing .NET 8 Desktop Runtime...
winget install --id Microsoft.DotNet.DesktopRuntime.8 -e --accept-package-agreements --accept-source-agreements --disable-interactivity
echo.
echo       Installing WebView2 Runtime...
winget install --id Microsoft.EdgeWebView2Runtime -e --accept-package-agreements --accept-source-agreements --disable-interactivity
echo.
echo       winget finished.

:launch
if not exist "MiniWarAFKBot.exe" (
  echo ERROR: MiniWarAFKBot.exe not found in this folder.
  pause
  exit /b 1
)

echo [3/3] Starting MiniWar AFK Bot...
start "" "%~dp0MiniWarAFKBot.exe"
echo.
echo Launcher started. You can close this window.
timeout /t 5 >nul
exit /b 0
