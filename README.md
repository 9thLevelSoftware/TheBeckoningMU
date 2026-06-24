# TheBeckoningMU

A **Vampire: The Masquerade 5th Edition** MUD built on [Evennia](https://www.evennia.com/) (Python/Django).

"The Beckoning" is the canonical event in V5 lore that calls elder vampires back to their home cities. The game implements the V5 dice system (Hunger dice, Rouse checks, Messy Criticals, Bestial Failures), character creation with clans, disciplines, predator types and resonances, plus a suite of supporting systems — BBS, jobs (staff requests), boons, status, traits, and a web-based builder for staff-authored content.

## Requirements

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended) or another PEP 621-compatible tool
- Evennia **5.x** (installed as a project dependency)

## Quick Start

Always run Evennia commands from the project root (`TheBeckoningMU/`), **not** from inside `beckonmu/`.

### With uv (recommended)

```bash
# Install dependencies
uv sync

# Activate the environment
source .venv/bin/activate

# Initialize the database (first run only)
evennia migrate

# Start the server
evennia start

# Stop / reload / check status
evennia stop
evennia reload
evennia status
```

### With pip + venv

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

evennia migrate
evennia start
```

The server is fully headless — connect with a telnet/MUD client or use the bundled web client.

## Access Points

Ports are configured in `server/conf/settings.py` (defaults shown below; override via `server/conf/secret_settings.py`):

| Service               | Default Port |
| --------------------- | ------------ |
| Telnet / MUD client   | `6660`       |
| Web server (HTTP)     | `5001`       |
| WebSocket client      | `6662`       |
| Web server proxy      | `6661`       |
| AMP (server-to-server)| `6670`       |

Web routes (assuming the default web port):

- **Web client**: `http://localhost:5001/webclient/`
- **Homepage / public site**: `http://localhost:5001/`
- **Character creation**: `http://localhost:5001/character-creation/`
- **Staff character approval**: `http://localhost:5001/staff/character-approval/`
- **Builder (staff)**: `http://localhost:5001/builder/`
- **Admin**: `http://localhost:5001/admin/`
- **API**: `http://localhost:5001/api/`

## Project Structure

```
TheBeckoningMU/
├── beckonmu/                # Main game code (importable Python package)
│   ├── bbs/                 # Bulletin-board system
│   ├── boons/               # Boon-tracking system
│   ├── commands/            # In-game commands (MuxCommand-based)
│   │   ├── v5/              # V5-specific commands
│   │   └── builder/         # Builder-related commands
│   ├── dice/                # V5 dice roller, rouse checks, discipline rolls
│   ├── jobs/                # Staff job/request tracker
│   ├── server/
│   │   └── conf/            # Evennia settings.py, cmdhandler, at_search
│   ├── status/              # Status / Influence tracking
│   ├── traits/              # Character trait system
│   ├── typeclasses/         # Account, Character, Room, Object, Exit, Script, Channel
│   ├── web/                 # Django apps: website, webclient, admin, api, builder
│   └── world/               # Game data (v5_data.py, v5_dice.py, ansi_theme, help, news)
├── server/                  # Evennia runtime (db, logs) — gitignored
├── world/                   # Root-level world helpers
├── pyproject.toml           # Project metadata + dependencies (uv/pip)
├── uv.lock                  # Locked dependency graph
├── .pre-commit-config.yaml  # ruff + formatting hooks
└── README.md
```

## Development

### Linting & formatting

[ruff](https://docs.astral.sh/ruff/) is configured in `pyproject.toml` (line length 120, rules `E F I N UP B C4 SIM`).

```bash
# Install the git hooks (once)
pre-commit install

# Run manually across the repo
pre-commit run --all-files

# Or invoke ruff directly
ruff check .
ruff format .
```

### Tests

```bash
pytest
```

Test modules live alongside the code they exercise (e.g. `beckonmu/dice/tests.py`, `beckonmu/jobs/tests.py`).

### Secrets & per-host config

Anything machine- or operator-specific (DB credentials, port overrides, secret keys) belongs in `server/conf/secret_settings.py`. That file is **not** committed.

## License

Not yet specified. Treat the codebase as **all-rights-reserved** unless a `LICENSE` file is added.
