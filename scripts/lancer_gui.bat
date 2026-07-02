@echo off
REM Lance l'interface graphique (depuis la racine du projet).
cd /d "%~dp0.."
python gui.py
if errorlevel 1 pause
