@echo off
setlocal
cd /d C:\Users\white\Desktop\MovingProject\KOSPI200_Project
py -m infrastructure.kis.kis_vts_weekday_collector
exit /b %ERRORLEVEL%
