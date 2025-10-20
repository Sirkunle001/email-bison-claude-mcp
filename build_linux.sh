#!/usr/bin/env bash
set -euo pipefail
python -m pip install --upgrade pip
pip install pyinstaller httpx python-dotenv mcp anyio
pyinstaller -F -n emailbison-mcp emailbison_mcp/__main__.py
echo "Build complete. Binary at: dist/emailbison-mcp"
