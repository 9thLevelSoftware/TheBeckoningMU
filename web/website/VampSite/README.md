# The Beckoning - Vampire: The Masquerade Website

This standalone static site provides public information and reference materials for The Beckoning. Django owns authenticated character creation, validation, persistence, and staff approval at `/character-creation/`.

## Character creation

The static pages `character-creation-new.html` and `character-creation.html` are retired entry points. They redirect to the Django character-creation page only when `PUBLIC_GAME_BASE_URL` is configured in `assets/js/site-config.js` to the canonical HTTPS game-site origin. Set the same origin as Django's `PUBLIC_GAME_BASE_URL` environment or deployment setting. If it is empty or invalid, these pages show an unavailable notice; they do not save characters in local storage or report a successful submission.

The homepage's **Create a Character** link uses the same deployment value. Set it only after the Django site is reachable.

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

## License

This project uses content from Vampire: The Masquerade 5th Edition, which is owned by Paradox Interactive. The website code is available under the MIT license.
