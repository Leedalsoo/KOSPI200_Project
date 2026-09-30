@echo off
cd /d C:\Users\white\Desktop\MovingProject\KOSPI200_Project
set PROJECT200_MARKET_DATA_DIR=kis_market_data_restart
C:\WINDOWS\py.exe -m scripts.kis_vts_websocket_collector
