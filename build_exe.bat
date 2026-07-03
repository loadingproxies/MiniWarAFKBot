@echo off
rem Build MiniWarAFKBot.exe into dist\MiniWarAFKBot\
cd /d "%~dp0"
python -m pip install pyinstaller --quiet
python tools\build_release.py --exe --zip-exe
echo.
echo Done. Run:  dist\MiniWarAFKBot\MiniWarAFKBot.exe
pause
