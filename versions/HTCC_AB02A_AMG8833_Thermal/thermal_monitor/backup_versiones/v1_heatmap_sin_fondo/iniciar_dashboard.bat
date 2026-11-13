@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Dashboard - Termocamara LoRaWAN AMG8833

REM ============================================================
REM  Dashboard web de la termocamara LoRaWAN AMG8833
REM  Levanta broker MQTT (1883) + servidor web (8080),
REM  y abre la pagina en el navegador.
REM ============================================================

set "PYTHON=C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe"
set "APP_DIR=C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor"
set "WEB_PORT=8080"
set "BROKER_PORT=1883"

echo ============================================
echo  Dashboard web - Termocamara AMG8833
echo  Broker MQTT : puerto %BROKER_PORT%
echo  Página web  : puerto %WEB_PORT%
echo ============================================
echo.

if not exist "%PYTHON%" (
    echo [ERROR] No se encontro Python en: %PYTHON%
    exit /b 1
)

REM ---------- Comprobar que el puerto 1883 este libre ----------
%PYTHON% -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',%BROKER_PORT%)); s.close()" >nul 2>&1
if %errorlevel% equ 0 (
    echo [AVISO] Ya hay un broker activo en %BROKER_PORT%. Se usara ese.
)

REM ---------- Lanzar el dashboard ----------
echo Iniciando dashboard...
start "Dashboard Termocamara" /min "%PYTHON%" "%APP_DIR%\dashboard.py" %WEB_PORT% %BROKER_PORT%

REM ---------- Esperar a que el servidor web responda ----------
set /a counter=0
:wait_http
%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%WEB_PORT%/health', timeout=1)" >nul 2>&1
if !errorlevel! equ 0 (
    echo Dashboard listo.
    goto open_browser
)
set /a counter+=1
if !counter! geq 20 (
    echo [WARNING] El dashboard no respondio a tiempo.
    goto done
)
timeout /t 1 /nobreak >nul
goto wait_http

:open_browser
REM ---------- Abrir la pagina en el navegador ----------
start "" "http://127.0.0.1:%WEB_PORT%/"
echo.
echo ============================================
echo  Dashboard abierto en el navegador.
echo  En otros dispositivos de la red usa:
echo    http://192.168.2.30:%WEB_PORT%/
echo  (el gateway UG56 publica a la IP 192.168.2.30)
echo ============================================

:done
timeout /t 3 /nobreak >nul
exit /b 0
