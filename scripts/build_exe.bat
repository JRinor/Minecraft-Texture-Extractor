@echo off
REM Construit un executable autonome MinecraftTextureExtractor.exe dans dist\
REM (se place a la racine du projet, quel que soit l'endroit d'ou on lance).
cd /d "%~dp0.."
python -m PyInstaller --noconfirm --onefile --windowed --name MinecraftTextureExtractor ^
  --collect-all tkinterdnd2 ^
  --collect-submodules extractor ^
  --paths . ^
  --add-data "profiles;profiles" ^
  gui.py
echo.
echo Termine. L'executable est dans : dist\MinecraftTextureExtractor.exe
pause
