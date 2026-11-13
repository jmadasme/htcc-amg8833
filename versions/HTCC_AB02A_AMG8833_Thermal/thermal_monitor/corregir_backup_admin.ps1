# -*- coding: utf-8 -*-
# corregir_backup_admin.ps1
# Agrega la cuenta 'backup' a los grupos correctos (espa\u00f1ol) y fuerza PasswordRequired.
$ErrorActionPreference = "Continue"
$log = "C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor\ssh_fix.log"
Start-Transcript -Path $log -Force

$u = Get-LocalUser -Name "backup" -ErrorAction SilentlyContinue

# Forzar que requiera contrasena y ponerla (por si no quedo)
if ($u) {
    $pw = ConvertTo-SecureString "Backup2026!" -AsPlainText -Force
    Set-LocalUser -Name "backup" -Password $pw -PasswordNeverExpires $true -ErrorAction SilentlyContinue
    Set-LocalUser -Name "backup" -PasswordNeverExpires $true -ErrorAction SilentlyContinue
    Write-Output "Contrasena asignada y expiracion desactivada"
}

# Agregar a grupos usando los nombres locales reales
foreach ($g in @("Administradores","Usuarios")) {
    if (Get-LocalGroup -Name $g -ErrorAction SilentlyContinue) {
        Add-LocalGroupMember -Group $g -Member "backup" -ErrorAction SilentlyContinue
        Write-Output "Agregado a grupo: $g"
    } else {
        Write-Output "GRUPO NO ENCONTRADO: $g"
    }
}

Write-Output "=== Verificacion ==="
Get-LocalUser -Name backup | Format-List Name,Enabled,PasswordRequired,PasswordNeverExpires
Write-Output "--- Grupos de backup ---"
$grps = Get-LocalGroup | Where-Object { (Get-LocalGroupMember -Group $_.Name -ErrorAction SilentlyContinue | Where-Object Name -like "*backup*") }
$grps | Select-Object -ExpandProperty Name

Stop-Transcript
Write-Output "DONE"
