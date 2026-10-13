# MOSAIC standalone GUI

This folder is self-contained and can be copied to a separate Git repository.
It uses Dash and Dash Bootstrap Components. It does not import the orchestrator,
read its databases, proxy authentication, or call ADA directly. Browser requests
go to the public MOSAIC backend using the backend's HttpOnly cookie.

## Local installation (Python 3.12–3.14)

From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
mosaic-gui
```

Open http://127.0.0.1:8050. Use the same host spelling as the backend; do not mix
localhost and 127.0.0.1. The backend defaults to http://127.0.0.1:8000.
After changing Python source, reinstall the GUI package before restarting.

The backend must already have:

```text
  MOSAIC_BROWSER_ALLOWED_ORIGINS=["http://127.0.0.1:8050"]
  MOSAIC_PILOT_AUTH_MODE=local
  MOSAIC_PILOT_AUTH_COOKIE_SECURE=false
```

Set those in the backend's environment, not the GUI. No administrator secret or
model credentials are needed in the GUI process. Node.js is only needed for the
JavaScript tests, not installation or running the app.

## GUI environment settings

```text
MOSAIC_GUI_BACKEND_URL                 Public API origin; default http://127.0.0.1:8000
MOSAIC_GUI_HOST                        GUI bind address; default 127.0.0.1
MOSAIC_GUI_PORT                        GUI bind port; default 8050
MOSAIC_GUI_ORGANISATION_LOGO_PATH       Optional private PNG path
MOSAIC_GUI_ORGANISATION_LOGO_WIDTH      Maximum PNG width; default 88 pixels
MOSAIC_GUI_ORGANISATION_LOGO_HEIGHT     Maximum PNG height; default 40 pixels
```

Keep the organisation PNG outside public assets, preferably in the ignored
private-branding/ directory, or mount it separately in deployment. Its aspect
ratio is preserved. No organisation image is included in this repository.
The header, sign-in screen and SVG favicon share the same modular M tangram:
left primary indigo #1e2a78; right darker indigo #16205d; pale inset pieces.
Bootstrap 5.3.8 CSS and the tangram are served locally. No CDN is needed.

## Behaviour

Sign-in checks the cookie and always opens a new conversation. History remains
available in the sidebar. Skills are grouped by the most-specific available
catalogue path, listed once, and are read-only. Descriptions expand on demand.
Both side panels collapse; desktop separators support pointer and arrow-key
resizing. Markdown supports headings, lists, tables and highlighted code blocks.
Raw HTML is disabled; the resource policy blocks external embedded images.
Reasoning and raw tool/SDK metadata are not shown.

Native ADK partial text is incremental; final aggregated text replaces the
partial turn instead of duplicating it. Only text is submitted. Conversation
switching and New conversation are disabled during streaming. Stop aborts the
request; the backend may permanently mark that conversation interrupted.
Interrupted history stays readable and its composer is disabled. No stream is
reconnected, replayed or automatically retried. Start a new conversation.

Sign-out clears the cookie through the backend and clears GUI user data. A
different token loads a different workspace. Stale responses from an earlier
sign-in cannot repopulate the UI. No token is placed in URLs, browser storage,
Dash stores or server callbacks; token entry uses a transient native input.
The GUI uses Waitress without debug/reloading. In local testing, browser cookies
share a host across ports; in deployment the backend cookie remains host-only
on its separate HTTPS hostname. Never log or commit cookie values.

## Deployment

Host the GUI separately from the backend. Configure their sibling HTTPS origins
under the same parent domain, set the backend's exact GUI allowlist, and retain
secure backend cookies. The GUI needs no extra reverse-proxy routing to ADA.
The optional Dockerfile builds this folder only, listens on port 8050 and runs
as a non-root user. Actual hosting, TLS, DNS and deployed browser checks remain
operator responsibilities; no deployment is performed by this code tranche.

## Tests

```sh
PYTHONPATH=src .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -q
node --test tests/test_adk_stream.mjs tests/test_api_client.mjs
```

BrowserFixtureBackend in tests/ is synthetic browser-QA data only. It is not
imported by the installed GUI and is not a fallback or demonstration mode in
the application. Browser checks against that fixture do not establish that
real ADA, provider execution or deployed cookie/CORS behaviour is working.
Complete functional testing against the actual backend before accepting the GUI.
