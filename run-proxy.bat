@echo off
REM Double-click or: run-proxy.bat [-HandoffOnly] [-ForceHandoff]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-proxy.ps1" %*
