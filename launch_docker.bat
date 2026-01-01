@echo off
SETLOCAL EnableDelayedExpansion

echo ==========================================
echo   AirDC++ Torznab Bridge Launcher
echo ==========================================

:: Verificar si Docker está instalado
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker no está instalado o no está en el PATH.
    echo Por favor, instala Docker Desktop desde https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

:: Detener contenedores previos si existen
echo [1/3] Deteniendo contenedores previos...
docker compose down

:: Construir la imagen
echo [2/3] Construyendo el contenedor...
docker compose build
if %errorlevel% neq 0 (
    echo [ERROR] Error durante la construcción del contenedor.
    pause
    exit /b %errorlevel%
)

:: Lanzar en modo interactivo para ver los logs inicialmente
echo [3/3] Lanzando el puente...
echo.
echo Presiona Ctrl+C para detener el bridge si es necesario.
echo.
docker compose up

pause
