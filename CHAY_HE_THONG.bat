@echo off
chcp 65001 >nul
title TRUNG TAM DIEU KHIEN PYSIDE6 (TU DONG QUAN LY SERVER & INTERNET)
echo =====================================================================
echo   KHOI DONG PHAN MEM PYSIDE6 (CO SAN NUT BAT/TAT SERVER & 4G/WIFI)
echo =====================================================================

cd /d "%~dp0"
start "Phan Mem PySide6" python pyside6_app\pyside6_main.py
