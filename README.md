# EmailBison MCP — Stand‑alone Binary (PyInstaller)

This package builds a **single-file executable** (per OS) so non-technical users can run the server without installing Python.

## Build (Windows)
Double‑click `build_windows.bat` or run:
```
build_windows.bat
```
Output: `dist\emailbison-mcp.exe`

## Build (macOS/Linux)
```
chmod +x build_macos.sh build_linux.sh
./build_macos.sh     # or ./build_linux.sh
```
Output: `dist/emailbison-mcp`

## Distribute to users
1. Send them the binary from the `dist/` folder.
2. In the same folder as the binary, create a `.env` file:
```
EMAILBISON_API_KEY=sk_live_...
EMAILBISON_BASE_URL=https://send.highticket.agency
```
3. Run the binary:
   - Windows: double-click `emailbison-mcp.exe`
   - macOS/Linux: `chmod +x emailbison-mcp && ./emailbison-mcp`

> macOS Gatekeeper may require notarization or running: `xattr -d com.apple.quarantine ./emailbison-mcp`

## Notes
- The executable bundles your code and Python runtime. Network access goes directly to EmailBison.
- Keep `.env` next to the binary (or set system env vars).
- If you want to ship signed binaries, build on each target OS and sign accordingly.


## First‑run prompt (optional)
When users launch the binary for the first time, if `EMAILBISON_API_KEY` and/or `EMAILBISON_BASE_URL` are not set,
the app will **prompt** them to enter values and will create a `.env` file **next to the binary**.
They can press Enter to skip; the binary will still run (but the server may warn if the API key is missing).
