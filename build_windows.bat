@echo off
REM Build stand-alone EXE with PyInstaller (Windows)
REM Usage: double-click or run in terminal.
python -m pip install --upgrade pip
pip install pyinstaller httpx python-dotenv mcp anyio
pyinstaller -F -n emailbison-mcp emailbison_mcp\__main__.py
echo.
echo Build complete. EXE at: dist\emailbison-mcp.exe
pause
