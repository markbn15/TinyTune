@echo off
title Compilando TinyTune
echo =======================================
echo === 1. Instalando dependencias ===
echo =======================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo =======================================
echo === 2. Limpiando compilaciones viejas ===
echo =======================================
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "TinyTune.spec" del /q "TinyTune.spec"

echo.
echo =======================================
echo === 3. Generando ejecutable ===
echo =======================================
python -m PyInstaller --noconfirm --onefile --windowed ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --collect-all customtkinter ^
    --collect-all pygame ^
    --name "TinyTune" ^
    tinytune.py

echo.
echo =======================================
echo === 4. Proceso terminado ===
echo =======================================
echo El ejecutable final esta en: dist\TinyTune.exe
pause