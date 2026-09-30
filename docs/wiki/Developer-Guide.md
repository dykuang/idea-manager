# Developer guide

## Stack and source layout

- `src/` — React and TypeScript UI.
- `backend/app/` — FastAPI routes, SQLite schema/migrations, search, Agent integration, and MCP tools.
- `backend/tests/` — backend API and MCP tests.
- `launcher.py` — coordinates the local API and frontend lifecycle.
- `packaging/` — Windows release builder and installer assets.
- `integrations/` — optional Codex skill.
- `data/` — ignored local runtime data; never add private library contents to a commit.

The SQLite database is authoritative. Preserve that design when adding features: keep related domain logic in focused backend modules and frontend components instead of growing `backend/app/main.py` or `src/App.tsx` unnecessarily.

## Set up and run

```bash
python -m venv .venv
# Activate .venv for your platform
python -m pip install -r backend/requirements.txt
npm ci
python launcher.py
```

## Build and checks

```bash
npm run build
npm run lint
python -m pytest backend/tests -q
```

The API's interactive documentation is available at `http://127.0.0.1:8000/docs` while the backend is running.

## Database changes

Schema changes belong in the idempotent initialization/migration flow. Keep existing user databases compatible. Add tests around migrations and API behavior for database features. Use isolated temporary databases in tests; never test against a user's live `data/ideaminer.db`.

## Release packaging

See [`packaging/README.md`](../../packaging/README.md) for release build, asset, install, update, and uninstall details. Follow the release checklist there and verify the app on a clean Windows profile before distributing a new package.

