import os, sys, json, platform
from pathlib import Path
from getpass import getpass
def is_frozen():
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
def app_dir():
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent.parent
def detect_claude_config():
    system = platform.system()
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA not set; cannot locate Claude config.")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        base = os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(base) / "Claude" / "claude_desktop_config.json"
def read_json_or_empty(p: Path):
    if p.exists():
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            return {}
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}
def write_json(p: Path, obj: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = p.with_suffix(p.suffix + f".bak_{ts}")
        try:
            p.replace(bak)
        except Exception:
            bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
def install_into_claude():
    cfg = detect_claude_config()
    data = read_json_or_empty(cfg)
    data.setdefault("mcpServers", {})
    if is_frozen():
        cmd_path = str(Path(sys.executable).resolve())
    else:
        cmd_path = str((app_dir() / "emailbison-mcp-macos").resolve())
    data["mcpServers"]["emailbison"] = { "command": cmd_path }
    write_json(cfg, data)
    print(f"Installed 'emailbison' MCP server into: {cfg}")
    print(f"Command set to: {cmd_path}")
    print("Restart Claude Desktop to load the new MCP server.")
def prompt_env_if_missing():
    has_key = bool(os.getenv("EMAILBISON_API_KEY"))
    has_url = bool(os.getenv("EMAILBISON_BASE_URL"))
    if has_key and has_url:
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    print("\n=== EmailBison MCP – First-run setup (optional) ===")
    print("Press Enter to skip any value and keep defaults.\n")
    key = os.getenv("EMAILBISON_API_KEY") or getpass("EMAILBISON_API_KEY: ")
    default_url = os.getenv("EMAILBISON_BASE_URL") or "https://send.highticket.agency"
    try:
        url = input(f"EMAILBISON_BASE_URL [{default_url}]: ").strip() or default_url
    except EOFError:
        url = default_url
    if not key and not url:
        print("No values entered. Skipping .env creation.\n"); return
    dotenv_path = app_dir() / ".env"
    try:
        with open(dotenv_path, "w", encoding="utf-8") as f:
            f.write(f"EMAILBISON_API_KEY={key}\nEMAILBISON_BASE_URL={url}\n")
        if key: os.environ["EMAILBISON_API_KEY"] = key
        if url: os.environ["EMAILBISON_BASE_URL"] = url
        print(f"\nSaved credentials to: {dotenv_path}\n")
    except Exception as e:
        print(f"Warning: could not write .env: {e}")
def cli():
    if "--install-claude" in sys.argv:
        try:
            install_into_claude()
        except Exception as e:
            print(f"Failed to install into Claude config: {e}")
        return
    prompt_env_if_missing()
    from .server import main as run_main
    import asyncio
    asyncio.run(run_main())
if __name__ == "__main__":
    cli()
