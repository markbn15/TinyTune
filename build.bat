@echo off
setlocal
cd /d "%~dp0"

echo Instalando dependencias...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Limpiando compilaciones anteriores...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo Generando ejecutable...
python -m PyInstaller --noconfirm --clean TinyTune.spec
if errorlevel 1 goto :error

echo.
echo Listo: dist\TinyTune.exe
pause
exit /b 0

:error
echo.
echo La compilacion fallo. Revisa el mensaje anterior.
pause
exit /b 1
