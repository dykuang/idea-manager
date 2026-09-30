# Install and get started

## Windows release installer

1. Download the latest `Install-IdeaMiner.bat` from [GitHub Releases](https://github.com/dykuang/idea-manager/releases/latest).
2. Run it and follow the prompts. The installer verifies the app archive checksum before installing.
3. Start **IdeaMiner** from the Start Menu. On first run it creates a local SQLite library.

The updater and installer do not need a separately installed Python or Node.js runtime. The app's release assets include the runtime they need.

## Run from source

For source installs, install Python 3.11+ and Node.js LTS, then run `start-ideaminer.bat` on Windows. On any platform, from the repository root:

```bash
python -m venv .venv
# Activate the environment (Windows: .venv\\Scripts\\Activate.ps1;
# macOS/Linux: source .venv/bin/activate)
python -m pip install -r backend/requirements.txt
npm ci
python launcher.py
```

The launcher coordinates the local API and web interface and opens the browser. The usual addresses are `http://127.0.0.1:5173` and `http://127.0.0.1:8000/docs`; if ports are occupied, use the addresses printed in the launcher window.

## First launch

IdeaMiner creates `data/ideaminer.db` and built-in `random_chat` and `recycle` projects. Create a research project, capture a thought, then add working notes, tags, files, figures, relations, or experiments as needed. Use `Ctrl+K` / `Cmd+K` to search and jump to common views.

## Interface modes

Choose **Classic** or **Studio** from **Appearance**. Studio adds a denser three-pane workspace. Theme and density preferences are stored in the browser and are separate from the database.

