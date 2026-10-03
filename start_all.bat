@echo off
REM ==========================================================================
REM  Smart Lab Monitor - start the whole connected system
REM    1. cloud database logger   (MQTT -> cloud\lab_data.db)
REM    2. virtual ESP32, or with   start_all.bat wokwi   the Wokwi simulation
REM       (the real firmware) is opened in your browser instead
REM    3. dashboard               (opens in your browser and auto-connects)
REM  Needs: Python with  pip install paho-mqtt numpy pandas
REM ==========================================================================
cd /d "%~dp0"

REM Paste your saved Wokwi project link here (Wokwi: sign in -> Save -> copy the URL)
set WOKWI_URL=https://wokwi.com/projects/476557350477755393

python -c "import paho.mqtt, numpy" 2>nul || (
  echo Installing Python packages paho-mqtt and numpy...
  python -m pip install paho-mqtt numpy pandas
)
start "Smart Lab - cloud logger" cmd /k "cd cloud && python -u mqtt_logger.py"
if /i "%1"=="wokwi" (
  if defined WOKWI_URL (
    start "" "%WOKWI_URL%"
    echo Wokwi opened - press the green Start button there.
  ) else (
    start "" "https://wokwi.com/projects/new/esp32"
    start "" explorer "%~dp0firmware"
    echo No saved Wokwi link yet: paste sketch.ino, diagram.json, model.h and
    echo libraries.txt from the firmware folder into Wokwi, then press Start.
    echo Save the project and put its link in WOKWI_URL at the top of this file.
  )
) else (
  start "Smart Lab - virtual ESP32" cmd /k "cd cloud && python -u virtual_device.py"
)
start "Smart Lab - dashboard server" /min cmd /k "python -m http.server 8765 --directory dashboard"
timeout /t 2 >nul
start "" "http://localhost:8765/#live"
echo.
echo All parts started. Close the three windows to stop everything.
