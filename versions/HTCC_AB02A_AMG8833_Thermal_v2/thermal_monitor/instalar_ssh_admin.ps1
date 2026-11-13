# -*- coding: utf-8 -*-
# instalar_ssh_admin.ps1
# Instala OpenSSH Server, abre el puerto 22 y crea la cuenta 'backup' (admin).
# Ejecutar como Administrador (o via Start-Process -Verb RunAs).

$ErrorActionPreference = "Continue"
$log = "C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor\ssh_install.log"
Start-Transcript -Path $log -Force

Write-Output "=== Instalando OpenSSH Server ==="
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Write-Output "Add-WindowsCapability exit: $LASTEXITCODE"

Write-Output "=== Iniciando servicio sshd ==="
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
Write-Output "Servicio: $((Get-Service -Name sshd).Status)"

Write-Output "=== Abriendo puerto 22 en firewall ==="
New-NetFirewallRule -Name "OpenSSH-Server" -DisplayName "OpenSSH Server (sshd)" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22

Write-Output "=== Creando cuenta local 'backup' ==="
$pw = Read-Host "Introduce la contrasena para la cuenta 'backup'" -AsSecureString
if (Get-LocalUser -Name "backup" -ErrorAction SilentlyContinue) {
    Write-Output "La cuenta 'backup' ya existe"
} else {
    New-LocalUser -Name "backup" -Password $pw -FullName "SSH Backup" -Description "Acceso SSH remoto total" -PasswordNeverExpires
    Write-Output "Cuenta 'backup' creada"
}
@("Users","Administrators") | ForEach-Object {
    Add-LocalGroupMember -Group $_ -Member "backup" -ErrorAction SilentlyContinue
}
Write-Output "Grupos de backup: $((Get-LocalUser -Name backup | Select-Object -ExpandProperty Enabled))"

Write-Output "=== Estado final ==="
Get-Service -Name sshd | Format-List Name,Status,StartType
Get-NetFirewallRule -Name "OpenSSH-Server" | Select-Object Name,Enabled

Stop-Transcript
Write-Output "DONE"
