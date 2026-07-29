# Fathom

Fathom is the frontend half of a meta-search setup built on [SearXNG](https://github.com/searxng/searxng). SearXNG does the actual searching (it queries a bunch of upstream engines and merges the results); Fathom is the page you type into and the layout the results land in. It's one HTML file, no framework, no build step, no npm anywhere in the picture. `frontend/index.html` has the CSS in a `<style>` block, the markup below it, and the JS in a `<script>` tag at the bottom. That's the whole app.

nginx serves that file and also acts as a reverse proxy for everything Fathom talks to: SearXNG itself, and a handful of small APIs used for instant-answer cards (weather, dictionary, music, news, place lookups). None of those extra calls touch your browser's default DNS or expose API keys client-side, they're proxied through nginx so the keys stay server-side.

## What it actually does

Type a query and you get SearXNG's aggregated results, split into tabs: web, images, news, videos, maps, code, science, music, files. Keys 1 through 9 jump between tabs. Search state (query, category, page, filters) is pushed into the URL, so a results page is a real bookmarkable/shareable link, not just client state that vanishes on refresh.

Before it even hits SearXNG, the query gets checked against a few local patterns for instant answers:

- Math expressions and unit conversions get computed inline (calculator, unit conversion cards).
- Dictionary lookups hit `api.dictionaryapi.dev` directly.
- Weather queries geocode through Nominatim and pull the forecast from `api.open-meteo.com`.
- Encyclopedia-style queries pull a summary card from Wikipedia's REST API.
- Place/location queries pull from Nominatim with extra tags for things like opening hours.
- Music queries go through the bundled Spotify proxy (see below).
- News queries go through NewsData.io.

There's also a bang syntax lifted from the DuckDuckGo/SearXNG convention: `w:query` jumps straight to Wikipedia, `gh:query` to GitHub, `yt:` to YouTube, `so:` to Stack Overflow, `r:` to Reddit, and a handful more defined in the `BANGS` object near the top of the script.

Maps are handled separately from the SearXNG results feed. A map query geocodes via Nominatim and pulls nearby points of interest from the Overpass API, with bounding-box and radius-widening logic so a vague query still returns something nearby if the exact match comes up empty.

The page also registers as a browser search provider via `opensearch.xml` and is installable as a PWA via `manifest.json`.

## Architecture

```
Browser ──GET /                          ──▶ nginx ──▶ frontend/index.html
Browser ──GET /searxng/search?q=…        ──▶ nginx ──proxy_pass──▶ SearXNG (external Docker network)
Browser ──GET /geoapify/...              ──▶ nginx ──▶ api.geoapify.com   (key injected server-side)
Browser ──GET /lastfm/...                ──▶ nginx ──▶ ws.audioscrobbler.com (key injected server-side)
Browser ──GET /newsdata/...              ──▶ nginx ──▶ newsdata.io        (key injected server-side)
Browser ──GET /spotify/v1/...            ──▶ nginx ──▶ spotify-proxy sidecar ──▶ api.spotify.com
Browser ──GET /vlm/...                   ──▶ nginx ──▶ self-hosted Qwen3-VL / llama.cpp endpoint
```

API keys (Geoapify, Last.fm, NewsData) never reach the browser. They're set as environment variables on the host, and `nginx.conf` is actually a template: the official nginx image runs `envsubst` on it at container start (`NGINX_ENVSUBST_FILTER` in `docker-compose.yml` restricts substitution to just those three variables, so nginx's own runtime variables like `$host` and `$args` are left alone).

The Spotify integration is a tiny stdlib-only Python sidecar (`spotify-proxy/app.py`, no dependencies beyond the standard library) that holds a cached `client_credentials` OAuth token, refreshes it ~30 seconds before expiry, and forwards `GET /v1/*` to `api.spotify.com` with the bearer token attached.

SearXNG itself is not part of this repo. It's expected to already be running as a separate Docker Compose project on an external network (`searxng_default`), which this compose file joins.

## Running it

```bash
# requires an existing SearXNG stack on the `searxng_default` external network,
# plus a .env with GEOAPIFY_API, LASTFM_API, NEWSDATA_API, SPOTIFY_CLIENT_ID,
# SPOTIFY_CLIENT_SECRET set
docker compose up -d --build

# after any change under frontend/, since the Dockerfile COPYs it in at build time
docker compose up -d --build

# after changing nginx.conf or the API key set
docker compose build --no-cache && docker compose up -d

# logs
docker compose logs -f fathom
```

Static assets (`favicon`, `og-banner`, etc.) live at `frontend/assets/` in the image, but the compose file bind-mounts `/docker/fathom/assets` over that path read-only at runtime, so you can drop in new images without a rebuild.

There's no lint, format, or test setup. It's a single HTML file and a stdlib Python script; editing either is just editing the file and rebuilding the container.

## Editing the frontend

Everything lives in `frontend/index.html`: CSS custom properties in `:root` for the color theme (cyan-on-dark, Rajdhani + Share Tech Mono from Google Fonts), the markup for the home and results views, and one script block with a `state` object and the render functions per category (`renderWeb`, `renderImages`, `renderNews`, and so on). No component split, no router library, no state management dependency, just `history.pushState` and a `popstate` handler keeping the URL and the UI in sync.
