@echo off
echo Starting Embroidery Server...
echo.
echo Drawings will be saved to: SewCustom folder
echo Server will run on: http://0.0.0.0:5000
echo.
echo To use from Kindle:
echo 1. Find your PC's IP address (run 'ipconfig')
echo 2. Open draw.html in Kindle browser
echo 3. Draw and click "Sew" button
echo.
echo Press Ctrl+C to stop the server
echo.
python sew_server.py
pause
