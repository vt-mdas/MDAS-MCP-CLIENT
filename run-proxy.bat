@echo off
REM Examples:
REM   run-proxy.bat
REM   run-proxy.bat -LoginOnly -Username USER -Password PASS
REM   run-proxy.bat -HandoffOnly
REM   run-proxy.bat -ForceHandoff
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-proxy.ps1" %*
