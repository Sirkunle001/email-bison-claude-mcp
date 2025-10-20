import os, sys
from pathlib import Path
from getpass import getpass

def is_frozen():
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

def app_dir():
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # repo root when not frozen

def prompt_env_if_missing():
    # Only prompt if both variables are missing and we are attached to a TTY
    has_key = bool(os.getenv("EMAILBISON_API_KEY"))
    has_url = bool(os.getenv("EMAILBISON_BASE_URL"))
    if has_key and has_url:
        return None  # nothing to do

    # If not a TTY (e.g., service or redirected), skip prompts.
    if not sys.stdin or not sys.stdin.isatty():
        return None

    print("\n=== EmailBison MCP – First‑run setup (optional) ===")
    print("We can create a .env file next to the binary so you don't have to set env vars manually.")
    print("Press Enter to skip any value and keep defaults.\n")

    key = os.getenv("EMAILBISON_API_KEY") or getpass("EMAILBISON_API_KEY: ")
    default_url = os.getenv("EMAILBISON_BASE_URL") or "https://send.highticket.agency"
    url = input(f"EMAILBISON_BASE_URL [{default_url}]: ").strip() or default_url

    # If user still left both empty, don't write .env
    if not key and not url:
        print("No values entered. Skipping .env creation.\n")
        return None

    # Write .env next to the executable (or project root when not frozen)
    target_dir = app_dir()
    dotenv_path = target_dir / ".env"
    with open(dotenv_path, "w", encoding="utf-8") as f:
        f.write(f"EMAILBISON_API_KEY={key}\n")
        f.write(f"EMAILBISON_BASE_URL={url}\n")

    # Reflect into current process so the server can read immediately
    if key: os.environ["EMAILBISON_API_KEY"] = key
    if url: os.environ["EMAILBISON_BASE_URL"] = url

    print(f"\nSaved credentials to: {dotenv_path}")
    print("You can edit this file later if needed.\n")
    return str(dotenv_path)

def cli():
    # Optional setup
    prompt_env_if_missing()

    # Defer import until after potential env write so dotenv can be loaded in server.main()
    from .server import main as run_main
    import asyncio
    asyncio.run(run_main())

if __name__ == "__main__":
    cli()
