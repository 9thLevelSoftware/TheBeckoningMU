# TheBeckoningMU

A **Vampire: The Masquerade 5th Edition** MUD built on [Evennia](https://www.evennia.com/) (Python/Django).

"The Beckoning" is the canonical event in V5 lore that calls elder vampires back to their home cities. The game implements the V5 dice system (Hunger dice, Rouse checks, Messy Criticals, Bestial Failures), character creation with clans, disciplines, predator types and resonances, plus a suite of supporting systems — BBS, jobs (staff requests), boons, status, traits, and a web-based builder for staff-authored content.

## Requirements

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Evennia **6.x** (installed by `uv sync` as a project dependency)

## Quick Start

The repository root **is** the Evennia game directory, so run every `evennia` command from here.

### First run

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Activate the environment:

   ```bash
   source .venv/bin/activate        # macOS / Linux
   .venv\Scripts\activate           # Windows (PowerShell or cmd)
   ```

   Or skip activation and prefix each command below with `uv run` (for example `uv run evennia migrate`). If PowerShell refuses to run the activation script ("running scripts is disabled on this system"), use `uv run` instead, or allow local scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

3. Create the untracked per-host files (`server/conf/secret_settings.py` with a fresh random `SECRET_KEY`, and `server/logs/`):

   ```bash
   evennia --initmissing
   ```

   The server refuses to start without `secret_settings.py`, or if its `SECRET_KEY` is still Evennia's public default. See `server/conf/secret_settings.example.py` for the other per-host settings (`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and the HTTPS cookie settings a public deployment needs).

4. Create the database:

   ```bash
   evennia migrate
   ```

5. Load the V5 trait reference data:

   ```bash
   evennia seed_traits
   ```

   > **Warning:** `evennia seed_traits --clear` deletes the trait tables *and every character's stored traits with them*. Never run it on a database you want to keep.

6. Start the server:

   ```bash
   evennia start
   ```

   The first start asks you to create the superuser account (the email is optional). This is the game owner's account.

7. Connect with a telnet/MUD client on port `6660`, or open the web client at `http://localhost:6665/webclient/`, and log in as the superuser. Players create characters on the website at `http://localhost:6665/character-creation/`; staff approve them at `/staff/character-approval/`.

### Day to day

```bash
evennia stop
evennia reload
evennia status
```

- After each `git pull`, run `evennia migrate` before starting the server.
- **Backups:** stop the server (`evennia stop`), then copy `server/evennia.db3`. The database is a single SQLite file.
- **Web builder access:** the builder currently admits any account with Django's `is_staff` flag. Until the builder's permission checks land, do not grant `is_staff` to builders you don't fully trust.

The server is fully headless. Connect with a telnet/MUD client or use the bundled web client.

## Access Points

Ports are configured in `server/conf/settings.py` (defaults shown below; override via `server/conf/secret_settings.py`):

| Service               | Default Port |
| --------------------- | ------------ |
| Telnet / MUD client   | `6660`       |
| Web server (HTTP)     | `6665`       |
| Web server (internal) | `5001`       |
| WebSocket client      | `6662`       |
| AMP (server-to-server)| `6670`       |

Web routes (assuming the default web port):

- **Web client**: `http://localhost:6665/webclient/`
- **Homepage / public site**: `http://localhost:6665/`
- **Character creation**: `http://localhost:6665/character-creation/`
- **Staff character approval**: `http://localhost:6665/staff/character-approval/`
- **Builder (staff)**: `http://localhost:6665/builder/`
- **Admin**: `http://localhost:6665/admin/`
- **Traits API**: `http://localhost:6665/api/traits/`

## Project Structure

The repo root is a standard Evennia game directory. Python imports are relative to it
(`from dice import ...`, `commands.command.Command`), with no package prefix.

```
TheBeckoningMU/
├── server/conf/         # settings.py, connection screens, lockfuncs, secret_settings.py (untracked)
├── typeclasses/         # Account, Character, Room, Object, Exit, Script, Channel
├── commands/            # MuxCommand-based commands + default_cmdsets.py
│   ├── v5/              # V5 commands; game logic lives in v5/utils/
│   └── builder/         # in-game sandbox commands for the web builder
├── dice/                # V5 dice roller, rouse checks, discipline rolls
├── bbs/ jobs/ status/ boons/ traits/   # Django apps (models + in-game commands)
├── web/                 # Django: website, webclient, admin, api, builder, templates, static
├── world/               # v5_data.py, ansi_theme.py, help/ and news/ text files
├── tests/               # cross-app tests (app-local tests live in each app)
├── pyproject.toml
└── uv.lock
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

Tests use Evennia's Django test runner. Settings now require `server/conf/secret_settings.py`, so run `evennia --initmissing` once in a fresh clone before testing:

```bash
evennia test --settings settings.py .                 # everything
evennia test --settings settings.py dice.tests        # one module
evennia test --settings settings.py jobs.tests.CmdJobsTests.test_list_all_jobs   # one test
```

Test modules live alongside the code they exercise (e.g. `dice/tests.py`, `jobs/tests.py`) plus cross-app tests in `tests/`.

### Secrets & per-host config

Anything machine- or operator-specific (port overrides, allowed hosts, the secret key) belongs in `server/conf/secret_settings.py`. That file is **not** committed. `evennia --initmissing` creates it, and `server/conf/secret_settings.example.py` documents what else can go in it.

## License

Not yet specified. Treat the codebase as **all-rights-reserved** unless a `LICENSE` file is added.
