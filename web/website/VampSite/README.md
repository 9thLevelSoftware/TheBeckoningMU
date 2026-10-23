# The Beckoning - Vampire: The Masquerade Website

This standalone static site provides public information and reference materials for The Beckoning. Django owns authenticated character creation, validation, persistence, and staff approval at `/character-creation/`.

## Character creation

The static pages `character-creation-new.html` and `character-creation.html` are retired entry points. They redirect to the Django character-creation page using the public origin generated from Django's `PUBLIC_GAME_BASE_URL` environment or deployment setting. If the generated value is empty or invalid, these pages show an unavailable notice; they do not save characters in local storage or report a successful submission.

The homepage's **Create a Character** link uses the same deployment value. Set it only after the Django site is reachable. Character creation is web-only; there is no in-game chargen command.

### Generate the deployment configuration

Configure `PUBLIC_GAME_BASE_URL` once in the environment or `server/conf/secret_settings.py`. Use the canonical HTTPS origin only, with an optional port and no path, credentials, query, or fragment. HTTP is accepted only for local development at `localhost`, `127.0.0.1`, or `[::1]`.

From the repository root, generate the asset before publishing the static site:

```powershell
.venv\Scripts\python.exe -m django build_public_site_config --settings server.conf.settings
```

The default output is `web/website/VampSite/assets/js/site-config.js`. For a separate static deployment directory, supply `--output <existing-directory>/site-config.js` and place the result at `assets/js/site-config.js` in that deployment. The command reads Django settings; it has no separate origin argument and makes no database changes. Do not maintain a second origin value by hand in the JavaScript asset.

An empty setting generates an empty assignment and leaves online character creation unavailable. An invalid setting stops the command before replacing any existing output. Writes use a temporary file and atomic replacement. The checked-in placeholder remains empty until an operator generates deployment configuration; no deployed origin is assumed.

Local checks (Node.js is needed only for the JavaScript tests):

```powershell
.venv\Scripts\evennia.exe test --settings settings.py traits.test_public_site_config
node --test web/website/VampSite/tests/game-link.test.cjs
```

After deployment, verify both retired URLs and the homepage CTA from the real static host, then verify that authenticated Django submission creates a pending character for staff approval.

## Chronicle and narrative

- Public staff-published entries: `/chronicle/`. Signed-in players can view their own participant entries at `/chronicle/mine/`.
- Optional AI-assisted hunt prose uses `+hunt/story opt-in` and can be stopped with `+hunt/story opt-out`. AI output is explicitly attributed, cannot change rules or character state, and does not publish to the Chronicle. Ordinary `+hunt` remains deterministic.
- The OAuth-protected MCP companion is read-only and account-scoped. It exposes public V5 lore/Chronicle plus the signed-in account's own Chronicle and owned character summaries; it cannot run game commands, roll dice, publish, or mutate state.
- AI generation and MCP access remain disabled until an operator configures the provider and exact public URLs/allowlists.

## Project structure

- `index.html` - Static-site homepage.
- `character-creation-new.html` and `character-creation.html` - Retired redirect entry points.
- `assets/js/site-config.js` - Deployment-supplied public game origin (`PUBLIC_GAME_BASE_URL`).
- `assets/js/game-link.js` - Validates the configured origin and routes to Django chargen.
- `assets/css/main.css` and `assets/js/main.js` - Homepage presentation and behavior.
- `references/` - V5 reference materials.

## Technologies

HTML5, CSS3, and JavaScript. The Django game site remains responsible for character data and account authorization.
## Project Structure

- `index.html` - Static-site homepage.
- `character-creation-new.html` and `character-creation.html` - Retired redirect entry points.
- `assets/js/site-config.js` - Deployment-supplied public game origin (`PUBLIC_GAME_BASE_URL`).
- `assets/js/game-link.js` - Validates the configured origin and routes to Django chargen.
- `assets/css/` and `assets/js/main.js` - Homepage presentation and behavior.
- `references/` - V5 reference materials.

The retired client-side character builders are not loaded by these pages. The static site is served outside Django; Django remains responsible for character data and account authorization.

## License

This project uses content from Vampire: The Masquerade 5th Edition, which is owned by Paradox Interactive. The website code is available under the MIT license.
