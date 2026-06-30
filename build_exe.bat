@echo off
REM Construit un executable autonome MinecraftTextureExtractor.exe dans dist\
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name MinecraftTextureExtractor ^
  --collect-all tkinterdnd2 ^
  --paths texture_extractor_v2 ^
  --hidden-import run --hidden-import matcher --hidden-import models ^
  --hidden-import dedupe --hidden-import packager --hidden-import profile_loader ^
  --hidden-import reporter --hidden-import pack_discovery --hidden-import contact_sheet ^
  --add-data "profiles;profiles" ^
  gui.py
echo.
echo Termine. L'executable est dans : dist\MinecraftTextureExtractor.exe
pause
