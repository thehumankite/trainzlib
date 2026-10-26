@echo off
REM Builds a single-file Windows executable: dist\TrainzLib.exe
REM Needs Python 3.9+ for Windows with internet access (to fetch PyInstaller and NumPy the first time).
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo Installing build tools...
%PY% -m pip install --upgrade pyinstaller numpy
if errorlevel 1 goto :fail

echo Building TrainzLib.exe ...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name TrainzLib ^
  --icon trainzlib.ico ^
  --add-data "trainzlib.ico;." ^
  --exclude-module matplotlib --exclude-module scipy --exclude-module pandas --exclude-module PIL ^
  trainzlib_gui.py
if errorlevel 1 goto :fail

echo.
echo Done: %~dp0dist\TrainzLib.exe
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up for the first error message.
pause
exit /b 1
