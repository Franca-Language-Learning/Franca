@echo off
rem Starts the Franca installer with administrator rights (story E01-011). Double-click this file.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File \"%~dp0Install-Franca.ps1\"'"
