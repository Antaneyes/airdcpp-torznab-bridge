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

if not exist .env (
    echo [ERROR] Falta .env. Copia .env.example como .env y configura los secretos.
    pause
    exit /b 1
)

echo [1/3] Validando la configuracion...
docker compose config --quiet
if %errorlevel% neq 0 (
    echo [ERROR] La configuracion de Docker Compose no es valida.
    pause
    exit /b %errorlevel%
)

echo [2/3] Descargando la imagen configurada...
docker compose pull
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo descargar la imagen.
    pause
    exit /b %errorlevel%
)

echo [3/3] Iniciando el bridge...
docker compose up -d
docker compose ps
echo.
echo Usa "docker compose logs -f --tail=200" para ver los logs.

pause
