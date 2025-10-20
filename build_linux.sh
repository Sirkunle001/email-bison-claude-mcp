#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller httpx python-dotenv mcp anyio
pyinstaller -F -n emailbison-mcp emailbison_mcp/__main__.py
echo "Built dist/emailbison-mcp"
