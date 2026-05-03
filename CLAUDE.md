# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a static website — "Raj's Robot Rentals" — a single-page quote generator for renting robots. There is no build system, no package manager, and no test framework. All files are plain HTML, CSS, and vanilla JavaScript.

## Serving the Site

Open `index.html` directly in a browser, or use any static file server:

```bash
python3 -m http.server 8080
# then visit http://localhost:8080
```

## Deployment

Pushes to `main` automatically deploy to GitHub Pages via the Jekyll workflow in `.github/workflows/jekyll-gh-pages.yml`. The repo root is served as-is (no Jekyll templating is used; Jekyll just passes through the static files).

## Architecture

The entire app lives in three files:

- **`index.html`** — single page; DOM structure for the quote generator. Inline text like model names and prices appear in both the `<ul>` list and in the JS constants — keep them in sync when changing pricing.
- **`scripts/scripts.js`** — all interactivity. Two independent button handlers (`changeModel`, `changeDuration`) each call `recalculate()` after mutating module-level `var` state (`modelName`, `duration`). The cost lookup is a ternary in `recalculate`: XYZ = $100/day, CPRG = $213/day.
- **`styles/styles.css`** — all custom styles; loads the "Press Start 2P" pixel font from Google Fonts. `styles/reset.css` is Meyer's CSS reset and should not be edited.

## Conventions

- JS uses `var` and classic DOM APIs (`getElementById`, `innerHTML`, `prompt`, `alert`) — stay consistent with this style rather than introducing ES6+ or frameworks.
- The `.flex` utility class (defined in `styles.css`) centers children with flexbox and is reused on both `<header>` and the button group in `<main>`.
- The footer is `position: fixed` at the bottom; account for this when adding content near the page bottom.
