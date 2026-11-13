@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Lanzador - Termocamara LoRaWAN AMG8833

REM ============================================================
REM  Lanzador de la aplicacion de monitor termico LoRaWAN
REM  Inicia el broker MQTT de consola (Python/amqtt, si no corre)
REM  y luego abre la app de escritorio.
REM ============================================================

set "PYTHON=C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe"
set "APP_DIR=C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor"
set "BROKER_PORT=1883"

echo ============================================
echo  Termocamara LoRaWAN AMG8833
echo  Preparando el entorno...
echo ============================================
echo.

REM ---------- 1) Python ----------
if not exist "%PYTHON%" (
    echo [ERROR] No se encontro Python en: %PYTHON%
    echo         Ajusta la variable PYTHON en este archivo .bat
    exit /b 1
)
echo [1/3] Python encontrado: OK

REM ---------- 2) Broker MQTT de consola ----------
REM Comprobar si ya hay un broker activo en el puerto (p.ej. Mosquitto)
%PYTHON% -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',%BROKER_PORT%)); s.close()" >nul 2>&1
if %errorlevel% equ 0 (
    echo [2/3] Broker MQTT ya activo en puerto %BROKER_PORT%
) else (
    echo [2/3] Broker MQTT no activo, iniciando broker de consola (amqtt)...
    start "Broker MQTT (amqtt)" /min "%PYTHON%" "%APP_DIR%\broker_consola.py" %BROKER_PORT%
    REM esperar a que el puerto se abra (max ~15 s)
    set /a counter=0
    :wait_loop
    %PYTHON% -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',%BROKER_PORT%)); s.close()" >nul 2>&1
    if !errorlevel! equ 0 (
        echo       Broker MQTT listo
        goto broker_ok
    )
    set /a counter+=1
    if !counter! geq 15 (
        echo [WARNING] El broker no abrio el puerto a tiempo. Continuando de todos modos.
        goto broker_ok
    )
    timeout /t 1 /nobreak >nul
    goto wait_loop
    :broker_ok
)

echo [3/3] Iniciando aplicacion de escritorio...
echo.

REM ---------- 3) Lanzar la app ----------
pushd "%APP_DIR%"
start "Termocamara AMG8833 - Monitor" "%PYTHON%" "%APP_DIR%\app.py"
popd

echo.
echo ============================================
echo  La aplicacion se esta abriendo...
echo  El gateway UG56 debe publicar por MQTT a
echo  la IP de este PC: 192.168.2.30 (puerto 1883)
echo ============================================
echo.

timeout /t 3 /nobreak >nul
exit /b 0
