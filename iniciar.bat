@echo off
echo ============================================
echo   Aftecnologia Store - Iniciando servidor
echo ============================================

cd /d "%~dp0"

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado.
    echo Descarga Python en https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Instalar tornado si no esta
pip show tornado >nul 2>&1
if errorlevel 1 (
    echo Instalando tornado...
    pip install tornado
)

REM Instalar pdfplumber si no esta
pip show pdfplumber >nul 2>&1
if errorlevel 1 (
    echo Instalando pdfplumber...
    pip install pdfplumber
)

REM Crear carpeta de uploads si no existe
if not exist uploads mkdir uploads

REM Inicializar base de datos (solo crea tablas si no existen)
python -B database.py

REM Arrancar servidor
echo.
echo Servidor listo en: http://localhost:8080
echo Panel admin en:    http://localhost:8080/admin
echo.
echo Presiona Ctrl+C para detener el servidor.
echo.
python -B server.py

pause
