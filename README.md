# TheBeckoningMU

A **Vampire: The Masquerade 5th Edition** MUD built on [Evennia](https://www.evennia.com/) (Python/Django).

"The Beckoning" is the canonical event in V5 lore that calls elder vampires back to their home cities. The game implements the V5 dice system (Hunger dice, Rouse checks, Messy Criticals, Bestial Failures), character creation with clans, disciplines, predator types and resonances, plus a suite of supporting systems — BBS, jobs (staff requests), boons, status, traits, and a web-based builder for staff-authored content.

## Requirements

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/) (recommended) or another PEP 621-compatible tool
- Evennia **6.x** (installed as a project dependency)

## Quick Start

The repository root **is** the Evennia game directory — run every `evennia` command from here.

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
| Web server (HTTP)     | `6665`       |
| Web server (internal) | `5001`       |
| WebSocket client      | `6662`       |
| AMP (server-to-server)| `6670`       |
| MCP companion (bind locally; proxy via TLS) | `8001` |

Web routes (assuming the default web port):

- **Web client**: `http://localhost:6665/webclient/`
- **Homepage / public site**: `http://localhost:6665/`
- **Character creation**: `http://localhost:6665/character-creation/`
- **Staff character approval**: `http://localhost:6665/staff/character-approval/`
- **Builder (staff)**: `http://localhost:6665/builder/`
- **Admin**: `http://localhost:6665/admin/`
- **API**: `http://localhost:6665/api/`

- **Public Chronicle**: `/chronicle/`
- **My Chronicle (signed in)**: `/chronicle/mine/`
- **Staff story operations**: `/staff/narrative-ops/`
- **OAuth authorization**: `/o/authorize/`, `/o/token/`, `/o/revoke_token/`
- **OAuth metadata**: `/.well-known/oauth-authorization-server/o`
- **MCP tools**: `/mcp` on the sidecar, with protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`

### Narrative and agent configuration

- Set `PUBLIC_GAME_BASE_URL` to the canonical HTTPS game origin in the Django deployment and the static site's `assets/js/site-config.js`. An empty or invalid value blocks static chargen redirects; Django remains the only persisted web submission path.
- Story generation is disabled unless `NARRATIVE_AI` is configured in `server/conf/secret_settings.py` with an OpenAI-compatible `endpoint`, `model`, and `api_key`. Remote endpoints must use HTTPS; loopback HTTP is allowed for local development.
- The MCP companion is a separate ASGI process: `uv run uvicorn web.mcp_service:app --host 127.0.0.1 --port 8001`. Keep it bound to loopback behind the TLS reverse proxy.
- Configure exact MCP deployment values (no wildcards):
  - `MCP_PUBLIC_URL=https://mcp.example.org/mcp` is the canonical MCP resource URL; optional `MCP_RESOURCE_URL` overrides it.
  - `MCP_OAUTH_ISSUER=https://game.example.org/o` identifies the Django OAuth issuer.
  - `MCP_ALLOWED_HOSTS=mcp.example.org` and `MCP_ALLOWED_ORIGINS=https://client.example.org` are exact request allowlists. Leave Origins unset for non-browser clients; browser Origins must be explicitly listed. The service rejects remote HTTP URLs, fails to start without the required URLs, and denies all requests if the host allowlist is absent.
- OAuth client registration is staff-controlled; Dynamic Client Registration is disabled. Register authorization-code clients and require PKCE. Tokens are short-lived, resource-bound, scoped, and revocable.
- The MCP exposes only five read tools for public V5 lore, public/personal Chronicle data, and caller-owned character summaries/status/boons. It cannot issue commands, roll dice, publish stories, or mutate character state.

## Project Structure

The repo root is a standard Evennia game directory. Python imports are relative to it
(`from dice import ...`, `commands.command.Command`), with no package prefix.

```
TheBeckoningMU/
├── server/conf/         # settings.py, connection screens, lockfuncs, secret_settings.py (untracked)
├── typeclasses/         # Account, Character, Room, Object, Exit, Script, Channel
├── commands/            # MuxCommand-based commands + default_cmdsets.py
│   ├── v5/              # V5 commands; game logic lives in v5/utils/
│   └── builder/         # sandbox / promote commands for the web builder
├── dice/                # V5 dice roller, rouse checks, discipline rolls
├── bbs/ jobs/ status/ boons/ traits/ chronicle/ narrative/   # Django apps
├── web/                 # Django: website, webclient, admin, API, builder, templates, static
├── mcp_server/          # OAuth-protected, read-only MCP companion
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

Tests use Evennia's Django test runner:

```bash
evennia test --settings settings.py .                 # everything
evennia test --settings settings.py dice.tests        # one module
evennia test --settings settings.py jobs.tests.CmdJobsTests.test_list_all_jobs   # one test
```

Test modules live alongside the code they exercise (e.g. `dice/tests.py`, `jobs/tests.py`) plus cross-app tests in `tests/`.

### Secrets & per-host config

Anything machine- or operator-specific (DB credentials, port overrides, secret keys) belongs in `server/conf/secret_settings.py`. That file is **not** committed.

## License

Not yet specified. Treat the codebase as **all-rights-reserved** unless a `LICENSE` file is added.
