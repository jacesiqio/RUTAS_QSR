@echo off
TITLE Ejecutor de Rutas-QSR y Auditoria de Datos
COLOR 0A
CLS

echo =====================================================================
echo   🚗 INICIANDO PIPELINE DE CONFIGURACION LOGISTICA | RUTAS-QSR
echo =====================================================================
echo.

:: 1. Validar la estructura interna de la base de datos con Python
echo [1/2] Ejecutando auditoria preventiva de esquemas en SQLite...
python check_vulnerabilities.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 🚨 ERROR: La verificacion de la base de datos ha fallado.
    echo Revisa el archivo check_vulnerabilities.py antes de continuar.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] Lanzando servidor local interactivo de Streamlit...
echo Interfaz lista. Abriendo navegador predeterminado...
echo.

:: 2. Arrancar la aplicacion web
python -m streamlit run app.py
