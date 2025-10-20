@echo off
python -m pip install --upgrade pip && pip install pyinstaller httpx python-dotenv mcp anyio
pyinstaller -F -n emailbison-mcp emailbison_mcp\__main__.py
echo Built dist\emailbison-mcp.exe
pause
