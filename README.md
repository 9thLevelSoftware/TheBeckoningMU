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

5. Start the server:

   ```bash
   evennia start
   ```

   The first start asks you to create the superuser account (the email is optional). This is the game owner's account.

6. Connect with a telnet/MUD client on port `6660`, or open the web client at `http://localhost:6665/webclient/`, and log in as the superuser. Players create characters on the website at `http://localhost:6665/character-creation/`; staff approve them at `/staff/character-approval/`.

### Day to day

```bash
evennia stop
evennia reload
evennia status
```

- After each `git pull`, run `evennia migrate` before starting the server.
- **Backups:** stop the server (`evennia stop`), then copy `server/evennia.db3`. The database is a single SQLite file.
- **Characters and approval:** players create characters only on the website (`/character-creation/`), which enforces the V5 core creation rules. A new character can't be played (no `ic`, rolls or XP) until staff approve it at `/staff/character-approval/`, which needs the in-game `Builder` permission on the account (`is_staff` grants nothing). Builders never approve their own character; Admins may, and every decision records the reviewer. Approval places the character in `START_LOCATION` (refused if that room doesn't exist). Admins can revoke an approval, which takes the character away from anyone playing it; the character keeps its sheet and XP, and the player resubmits it for review as it stands. Each application has a job in the `Approval` bucket that follows it (commented on each decision, closed on approval or deletion). The approval page flags an application made from the reviewer's own address (shown to staff only); approving a character on your own second account is forbidden. That flag is a hint only, and only meaningful behind a trusted front proxy (see Deployment notes below). `traits` migration 0003 re-locks every existing character with the approval gate, so staff NPCs made before it need `@lock <obj> = puppet:perm(Builder)` again. Players can delete their own pending characters with `chardelete`. For a staff NPC: `@create <name>:typeclasses.characters.Character`, then `@lock <name> = puppet:perm(Builder)`, then `@set <name>/splat = mortal` (or `ghoul`; unset means vampire). Staff read all of this in game with `help staff-approval` (Builders and above only).
- **Web builder access:** the web builder (`/builder/`) and its review page require the in-game `Builder` permission or higher (grant it on the **account** in game with `perm *<account> = Builder`; without the `*` the permission lands on a character, which the website ignores). Django's `is_staff` flag grants nothing there. Builders can review other people's projects but never their own; Admins and above may approve their own, and every review records who made it (shown under "Recently Reviewed" on the review page). A project's map and its live connection room are locked once it is submitted, and the sandbox is built from the snapshot taken at approval. Promotion connects the area to the reviewed room and direction only. Cleanup (the dashboard's "Clean up" button or `@cleanup_sandbox <id>`) deletes only the rooms and exits that project's build created, refuses while a character is inside, and keeps the project so it can be built again. Only drafts can be deleted by their owner; Admins can delete any project that has no sandbox (clean the sandbox up first). Builder text may use colour codes but not link markup (`|lc`, `|lu`).

- **Databases made before the October 2026 rules update:** wipe them (this is pre-launch). Older dev databases keep data the current code ignores or refuses: a stale top-level `hunger` Attribute and integer `pools` on characters, owner-puppet character locks from before `traits` 0003, `built` builder projects with no recorded object ids (reset them to `approved` and delete their old `project_N`-tagged rooms by hand). (Old `NORMAL` job priorities are fixed by `jobs` migration 0002.) Re-create characters and builder projects made before then.
- **Help and news** are text files under `world/help/<category>/` and `world/news/<category>/`. Long guides end in `-guide` (`help roll-guide`, `help hunger-guide`) so they don't share a key with a command; `help v5-rules-guide` is the one rules summary. Staff-only entries are YAML files with `read`/`view` locks (`world/help/staff/staff-approval.yaml`). `tests/test_help_integrity.py` fails if a file names a command, switch or topic that doesn't exist.

- **Deployment notes (client addresses):** Evennia's Portal proxies web requests to the Server from 127.0.0.1 without an `X-Forwarded-For` header, and the Server trusts the first `X-Forwarded-For` entry from any address in `UPSTREAM_IPS` (default `["127.0.0.1"]`). So without a front proxy every request looks like 127.0.0.1, and a client can forge its address by sending the header itself. For recorded applicant/reviewer addresses to mean anything, run a trusted reverse proxy (nginx, Caddy) that *overwrites* `X-Forwarded-For` with the real client address (nginx: `proxy_set_header X-Forwarded-For $remote_addr;`, not `$proxy_add_x_forwarded_for`), and set `UPSTREAM_IPS` in `secret_settings.py` to that proxy only. Loopback addresses are never flagged as "same origin". The flag is a hint for staff; `reviewed_by` and the staff policy are the control.

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
- **Builder (in-game `Builder` permission)**: `http://localhost:6665/builder/`
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
