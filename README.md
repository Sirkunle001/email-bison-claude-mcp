# EmailBison MCP (one-file app)

A stand-alone **MCP server** for EmailBison, packaged as a single binary for **Windows / macOS / Linux**.  
No Python required. On first run, it can **prompt** for your API key & base URL and create a local `.env`.

> **MCP** (Model Context Protocol) lets desktop AI apps—like **Claude Desktop**—call external tools.  
> This app exposes EmailBison tools (campaigns, replies, leads, warmup, events, etc.) to Claude.

---

## ✅ Before you start (required)

1) **Install Claude Desktop**  
   Download and install for your OS from Anthropic:
   - **Claude Desktop (macOS/Windows)**: https://www.anthropic.com/claude/desktop  
   Open it once to finish setup, then quit it— we’ll connect the MCP server next.

2) **Have your EmailBison API key**  
   Per-workspace keys are recommended. Keep it handy.

---

## 🚀 Quick Start (most users)

1) **Download** from the repo’s **[Releases](../../releases)** page:
   - Windows → `emailbison-mcp-windows.exe`
   - macOS → `emailbison-mcp-macos`
   - Linux → `emailbison-mcp-linux`

2) **One-shot install into Claude (recommended)**  
   Run **once** with `--install-claude` to auto-register this MCP server in Claude’s config (backs up the file and merges safely), then exit.

   - **Windows (PowerShell)**  
     ```powershell
     .\emailbison-mcp-windows.exe --install-claude
     ```
   - **macOS**  
     ```bash
     chmod +x ./emailbison-mcp-macos
     ./emailbison-mcp-macos --install-claude
     ```
   - **Linux**  
     ```bash
     chmod +x ./emailbison-mcp-linux
     ./emailbison-mcp-linux --install-claude
     ```

3) **Run the server normally**
   - Windows: double-click `emailbison-mcp-windows.exe`
   - macOS/Linux:
     ```bash
     ./emailbison-mcp-macos     # or: ./emailbison-mcp-linux
     ```

4) **First-run prompt (optional)**  
   If no env vars are present, the app offers to create a `.env` **next to the binary**:
   - `EMAILBISON_API_KEY` (hidden input)
   - `EMAILBISON_BASE_URL` (default: `https://send.highticket.agency`)  
   Press **Enter** to skip a field. If you enter values, they’re saved and used immediately.

> Prefer manual setup? Create a `.env` next to the app:
> ```
> EMAILBISON_API_KEY=sk_live_...
> EMAILBISON_BASE_URL=https://send.highticket.agency
> ```

5) **Open/Restart Claude Desktop**  
   After step 2 (or after manual config), restart Claude Desktop.  
   You should see **emailbison** available as a tool source.

---

## 🧭 Using it in Claude Desktop

With the server running, try prompts like:

- “**list campaigns**”
- “**analyze campaign 12345** (include replies and sequence)”
- “**analyze replies for campaign 12345**”
- “**create campaign named Q4 Outbound**”
- “**add leads [101,102,103] to campaign 12345 (allow parallel sending)**”
- “**stop future emails for leads [201,202] in campaign 12345**”
- “**list warmup accounts**” → “**enable warmup for sender IDs [5,6]**”
- “**raw request GET /api/replies with filters …**” (debug)

---

## 🔧 What’s included (tools)

- Campaigns: `list_campaigns`, `analyze_campaign`, `campaign_performance_summary`
- Replies: `analyze_replies`, `dump_replies_json` (debug)
- Leads: `lead_engagement_analysis`, `add_leads_to_campaign`, `stop_future_emails`
- Sequence: `sequence_optimization_insights`
- Events: `campaign_events_stats`
- Email accounts / warmup: `list_email_accounts`, `list_warmup_accounts`, `warmup_account_details`, `warmup_enable`, `warmup_disable`, `warmup_update_limits`
- Debug: `raw_request` (any HTTP method + path + params/body)

The server prints concise HTTP diagnostics (retries, 422 details, JSON/HTML safety) in the console.

---

## 🧩 Manual Claude config (only if you skip `--install-claude`)

Claude config locations:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Add/merge:
```json
{
  "mcpServers": {
    "emailbison": {
      "command": "/absolute/path/to/emailbison-mcp-macos"
      /* Optional if not using .env:
      ,"env": {
        "EMAILBISON_API_KEY": "sk_live_...",
        "EMAILBISON_BASE_URL": "https://send.highticket.agency"
      }
      */
    }
  }
}
```
Windows example:
```json
"command": "C:\\Users\\YOU\\Downloads\\emailbison-mcp-windows.exe"
```
Restart Claude Desktop after editing.

---

## 🆘 Troubleshooting

- **First, ensure Claude Desktop is installed.**  
  Install it before running `--install-claude` or starting the server.

- **Claude doesn’t see the tool**  
  - Make sure the **server app is running** (leave the window open).
  - If you used `--install-claude`, **restart Claude Desktop** afterwards.
  - On manual config, confirm the **absolute path** to the binary is correct.

- **Unauthorized / missing key**  
  Put a `.env` next to the app or set system env vars, then relaunch.

- **macOS “can’t be opened” (unidentified developer)**  
  Control-click → Open once, or:
  ```bash
  xattr -d com.apple.quarantine ./emailbison-mcp-macos
  ```

- **422 / API errors**  
  The console shows the first ~2 KB of error body + JSON fields.  
  Use `raw_request` to probe exact endpoints/params quickly.

---

## 🗑 Uninstall

There’s no installer—just delete files:

1) Close the server window.  
2) Delete the binary (`emailbison-mcp-*`).  
3) Delete the local `.env` next to it (if present).  
4) Remove any shortcuts/symlinks you created.

---

## 🔐 Security & multiple workspaces

- Treat your **API key** like a password.  
- For multiple EmailBison workspaces, either:
  - keep separate folders, each with its own `.env`, **or**
  - add multiple entries in Claude’s config, each with its own `env` block.
- Rotate keys periodically.

---

## 🧱 Build your own binaries (maintainers)

- **Windows:**  
  Double-click `build_windows.bat` (produces `dist/emailbison-mcp.exe`)
- **macOS/Linux:**  
  ```bash
  chmod +x build_macos.sh build_linux.sh
  ./build_macos.sh     # or: ./build_linux.sh
  ```
Outputs land in `dist/`.

### CI (optional): GitHub Release auto-builds
If you’ve added the provided GitHub Actions workflow, push a tag (e.g., `v0.3.0`) to build and attach binaries to a Release.

---

## 📄 License & Support

- License: MIT (or your chosen license)  
- Issues: please include OS, steps taken, and the last ~30 lines of console output (remove secrets)

---

### FAQ

**Do I need Python?**  
No. The binary includes everything.

**Which base URL should I use?**  
Usually `https://send.highticket.agency` unless your EmailBison instance is different.

**Can I run it in the background?**  
Yes—advanced users can run as a service (systemd on Linux, Task Scheduler on Windows), but most users just leave the window open while using Claude.
