# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A Vampire: The Masquerade 5th Edition MUD on **Evennia 6.x** (Django 6 + Twisted), Python 3.12+, managed with `uv`.

## Commands

The repo root is the Evennia game directory, so run everything from here. With the venv active use `evennia ...`; otherwise use `uv run evennia ...` (on Windows, `.venv\Scripts\evennia`).

```bash
uv sync                                   # install (incl. dev group)
evennia --initmissing                     # once per clone: creates server/conf/secret_settings.py + server/logs/
evennia migrate                           # first run, after model changes, and after every pull
evennia start                             # first start prompts for the superuser
evennia reload
evennia stop
evennia status
evennia makemigrations <app>              # bbs, jobs, status, boons, traits, builder
evennia seed_traits                       # populate the traits DB (traits/management/commands/)

evennia test --settings settings.py .                              # all tests
evennia test --settings settings.py dice.tests                     # one module
evennia test --settings settings.py jobs.tests.CmdJobsTests.test_list_all_jobs   # one test

ruff check . && ruff format .             # also run by pre-commit (pre-commit run --all-files)
```

- `server/conf/settings.py` refuses to load (ImproperlyConfigured) if `server/conf/secret_settings.py` is missing or its `SECRET_KEY` is still Evennia's default. That applies to every `evennia` command, tests included, so run `evennia --initmissing` first in a fresh clone or worktree. `server/conf/secret_settings.example.py` documents the other per-host settings.
- `evennia seed_traits --clear` deletes the trait tables, and every character's `CharacterTrait`/`CharacterPower` rows cascade with them. Never run it on a database you want to keep.
- The database is the single SQLite file `server/evennia.db3`. Back up by stopping the server and copying it.
- Web authority uses Evennia permission strings, not Django's `is_staff`: `web/permissions.has_perm(user, perm)` wraps `check_permstring` (superusers pass). The web builder requires `Builder` on the account (`perm *<account> = Builder`).
- Tests run through Evennia's Django runner (there is no pytest setup). Command tests must subclass `evennia.utils.test_resources.EvenniaCommandTest` to get `self.call`.
- The suite already has many failures. For example, the `jobs.tests` command tests call `self.call` but subclass `BaseEvenniaTest` (which has no `.call()`) instead of `EvenniaCommandTest`, and much of `tests/` fails too. Compare against the failure set before your change, not against a green suite.
- Ports: telnet 6660, web **6665** (browser-facing; 5001 is internal), websocket 6662, AMP 6670. Per-host overrides and secrets go in `server/conf/secret_settings.py` (untracked).

## Architecture

**Import root.** Modules import relative to the repo root with no package prefix (`from dice import dice_roller`, `commands.command.Command`, `INSTALLED_APPS += ("bbs", "jobs", ...)`). Do not add a `beckonmu.` prefix. That directory was flattened into the root.

**Commands.** `COMMAND_DEFAULT_CLASS = "commands.command.Command"`, a `MuxCommand` subclass with styled error/usage helpers; every game command inherits from it. To make a command available, add it in `commands/default_cmdsets.py`. The cmdsets import lazily inside `at_cmdset_creation` and also merge the per-system cmdsets (`dice.cmdset.DiceCmdSet`, `bbs.commands.BBSCmdSet`, `jobs.cmdset.JobsCmdSet`, `commands.v5.blood_cmdset.BloodCmdSet`). V5 command classes in `commands/v5/*.py` are thin; the mechanics live in `commands/v5/utils/*_utils.py` and `dice/`. Unknown-command styling comes from `commands/system_commands.SystemNoMatch`. Evennia's `charcreate` is removed from `AccountCmdSet` (characters are created only on the website), and there is no in-game chargen. `@promote`/`@abandon` are gone and `@cleanup_sandbox` is unregistered until cleanup works from recorded object ids.

**Character state lives in Attributes, not models.** `typeclasses/characters.py` initializes nested dicts on `char.db`: `stats` (attributes/skills/disciplines/specialties), `vampire` (clan, generation, blood potency, hunger, humanity), `pools`, `humanity_data`, `advantages`, `experience`, `effects`/`active_effects`, and `chargen`. Hunger was once stored as a legacy top-level `db.hunger`. The `hunger` property and `migrate_vampire_data()` keep the two in sync, so go through the property.

**Two sources of V5 reference data.** Static data lives in `world/v5_data.py` and `world/vtm5e_data/*.json`. The DB-backed `traits` app (models `TraitCategory`/`Trait`/`DisciplinePower`/`CharacterTrait`, seeded by `seed_traits`) serves the web. Check which one a code path reads before changing rules data.

**Django apps.** `bbs`, `jobs`, `status`, `boons`, `traits` each follow the pattern `models.py` + `commands.py` (in-game) + `utils.py` + `migrations/`. `web/urls.py` mounts `web.website` (homepage, `/character-creation/`, `/staff/character-approval/`), `webclient`, `admin`, `api/traits/` (→ `traits.urls`: trait lists plus character create/validate/export/approval/resubmit endpoints; there is no import endpoint), and `builder/`. Web chargen flow: the page at `/character-creation/` posts to `/api/traits/character/create/`, which creates the Character plus a `traits.CharacterBio` awaiting approval (listed at `/api/traits/pending-characters/`), and staff approve it through `/api/traits/character/<id>/approval/`. `AUTO_CREATE_CHARACTER_WITH_ACCOUNT = False` and `MULTISESSION_MODE = 3`.

**Web builder** (`web/builder/`). A `BuildProject` stores a whole area as a JSON map blob with a status lifecycle. `sandbox_builder` creates real Evennia rooms/exits from that JSON. Review rules: Builders never approve or reject their own project (Admins and above may), and `reviewed_by`/`reviewed_at` are always recorded and listed on the review page. `map_data` saves (including `RoomTriggersAPI`) are allowed only in `draft` (a rejection returns a project to draft), and they need the current `version`. Approve/reject also need the `version` the reviewer saw and are conditional updates on `status=submitted` (409 if stale). Owners may delete only drafts; Admins may delete any project. Django admin shows the review record and snapshot read-only. Submit requires a live `connection_room_id` + `connection_direction` (`validators.validate_connection`). Approval snapshots `{map_data, connection_room_id, connection_direction}` into `approved_map_data`, and the sandbox build reads only that snapshot. Build, cleanup and promote are owner-or-Admin. The editor receives the map through `json_script`; never render builder data with `|safe` or into inline handlers. Because Django views run outside the game loop, every Evennia object mutation from web code must go through `sandbox_bridge` (`run_in_main_thread`). `promotion.py` moves a reviewed sandbox into the live world and creates the connecting exits. `trigger_*`/`v5_conditions.py` implement room triggers. There is no `.ev` export, and the web sandbox-cleanup route is unrouted until cleanup works from recorded object ids. The in-game counterparts are in `commands/builder/`.

**Help and news** are file-based (`docs/legacy-help/` is an unloaded archive). `world/help_entries.py` and `world/news_entries.py` load `world/help/<category>/*.txt` and `world/news/<category>/*.txt`. Command docstrings are also help, so avoid giving a file entry the same key as a command.

**Migrations.** Always name the app (`evennia makemigrations traits`). A bare `makemigrations` can write proxy-model migrations into the installed Evennia package's own `objects` app. That has happened here before: app migrations once depended on a nonexistent `objects.0014`. Evennia's latest `objects` migration is `0013`.

**`web/website/VampSite/`** is a standalone static site (plain HTML/SCSS/JS, served outside Django; the `.shtml` error pages and `cgi-bin/` are for a traditional web host). Character creation happens on the game website: `index.html` and the two creation pages (`character-creation-new.html`, `character-creation.html`) only link to the game website's `/character-creation/` form (the game URL is set in one place; see its README). The old client-side builder JS (`assets/js/character-sheet*.js`) is no longer loaded but is kept. It also holds the owner's V5 reference PDFs. Django doesn't route to it, but it is not dead code, so don't delete it.
