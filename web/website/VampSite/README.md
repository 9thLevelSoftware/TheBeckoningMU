# The Beckoning - Vampire: The Masquerade Website

A static website for "The Beckoning", an Athens By Night Vampire: The Masquerade chronicle. It is plain HTML/CSS/JS served outside Django (the `.shtml` error pages and `cgi-bin/` are for a traditional web host).

## Character Creation

Character creation happens on the game website. The pages here (`character-creation-new.html` and the older `character-creation.html`) only explain that and link to the game's `/character-creation/` form, where players build a character and submit it for staff approval. The homepage's "Create a Character" button links there too.

These static pages no longer validate creation rules or produce character JSON, and the game has no import path for pasted character data.

## Project Structure

- `index.html` - Main landing page
- `character-creation-new.html`, `character-creation.html` - Pointers to the game website's character creation form
- `assets/css/` - CSS stylesheets (`main.css` is the site style)
- `assets/js/` - JavaScript files
  - `main.js` - Main site functionality
  - `character-sheet.js`, `character-sheet-new.js` - The retired client-side character builder. No page loads them any more; they are kept for reference.
- `references/` - V5 reference materials (PDFs)

## License

This project uses content from Vampire: The Masquerade 5th Edition, which is owned by Paradox Interactive. The website code is available under the MIT license.
