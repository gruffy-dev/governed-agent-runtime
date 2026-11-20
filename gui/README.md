# MOSAIC standalone GUI

This folder is self-contained and can be copied to a separate Git repository.
It uses Dash and Dash Bootstrap Components. It does not import the orchestrator,
read its databases, proxy authentication, or call ADA directly. Browser requests
go to the public MOSAIC backend using the backend's HttpOnly cookie.

## Local installation (Python 3.12–3.14)

On macOS or Linux, run from this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
mosaic-gui
```

On Windows, run from this folder in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
.\.venv\Scripts\mosaic-gui.exe
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
MOSAIC_GUI_SCHEME                      http (default) or https (macOS/Linux)
MOSAIC_GUI_TLS_CERT_FILE               PEM server certificate followed by intermediates
MOSAIC_GUI_TLS_KEY_FILE                Matching unencrypted PEM private key
MOSAIC_GUI_ORGANISATION_LOGO_PATH       Optional private PNG path
MOSAIC_GUI_ORGANISATION_LOGO_WIDTH      Maximum PNG width; default 88 pixels
MOSAIC_GUI_ORGANISATION_LOGO_HEIGHT     Maximum PNG height; default 40 pixels
```

## HTTPS listener

On macOS and Linux, the GUI uses Gunicorn with one supervised worker and four
request threads. On Windows, it uses Waitress with four request threads for
local HTTP. A Windows GUI configured for HTTPS stops with a configuration
error.

HTTP remains the default for local development and deployments with upstream
TLS termination. Gunicorn can also serve HTTPS directly, including when a
deployment forwards TLS through to the GUI. To enable that listener on macOS
or Linux:

```sh
export MOSAIC_GUI_SCHEME=https
export MOSAIC_GUI_TLS_CERT_FILE=/path/to/fullchain.pem
export MOSAIC_GUI_TLS_KEY_FILE=/path/to/private.key
export MOSAIC_GUI_BACKEND_URL=https://api.example.com
mosaic-gui
```

Replace the example API origin with the configured Apigee HTTPS origin. The
browser contacts that origin directly and validates its certificate using its
normal trust settings. The GUI server does not call Apigee or disable certificate
verification. No orchestrator code changes are needed.

The certificate must cover the GUI hostname in its Subject Alternative Names.
Supply the server certificate and intermediate chain in PEM format. Both TLS
files are required in HTTPS mode. Missing, unreadable, malformed or mismatched
files stop startup; there is no fallback to HTTP. Keys must be unencrypted to
allow unattended startup, protected by filesystem permissions and readable only
by the service account where practical. Gunicorn also loads the files when
starting workers. Configuration validation does not check certificate expiry or
browser trust; verify those with a trusted client.

Keep all TLS material outside Git and images, and mount it read-only for
deployment. The standalone GUI ignore rules also exclude common certificate and
key extensions and private-tls/. Restart the GUI after replacing certificates.
The existing MOSAIC_GUI_PORT selects the port for either protocol; HTTPS does not
automatically select port 443. Only one protocol is served, with no HTTP redirect
listener. HTTP mode rejects TLS file settings to catch accidental misconfiguration.

### Local self-signed HTTPS test

Generate test material outside the repository (requires OpenSSL with -addext):

```sh
mkdir -p "$HOME/.mosaic-gui-tls"
chmod 700 "$HOME/.mosaic-gui-tls"
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -keyout "$HOME/.mosaic-gui-tls/localhost.key" \
  -out "$HOME/.mosaic-gui-tls/localhost.pem" \
  -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1'
chmod 600 "$HOME/.mosaic-gui-tls/localhost.key"
export MOSAIC_GUI_SCHEME=https
export MOSAIC_GUI_TLS_CERT_FILE="$HOME/.mosaic-gui-tls/localhost.pem"
export MOSAIC_GUI_TLS_KEY_FILE="$HOME/.mosaic-gui-tls/localhost.key"
mosaic-gui
```

In another terminal, verify the certificate and response without bypassing TLS:

```sh
curl --noproxy '*' --cacert "$HOME/.mosaic-gui-tls/localhost.pem" \
  https://localhost:8050/
```

For browser testing, import only localhost.pem into your local certificate trust
store and explicitly trust it for SSL (on macOS, use Keychain Access). Never
import or share the private key. Browser trust settings vary; remove the test
certificate when finished. Open https://localhost:8050 and check that the page
and assets load without certificate warnings. This check does not need a backend.

For login and chat tests, set MOSAIC_GUI_BACKEND_URL to an HTTPS Apigee endpoint or
a local HTTPS reverse proxy in front of the existing HTTP backend. The browser
must trust the API certificate too. Do not depend on browser-specific HTTP
loopback exceptions: mixed-content, local-network and cookie restrictions can
prevent an HTTPS GUI from using an HTTP API. The backend's allowed browser origin
must match https://localhost:8050 exactly for this test, and its cookie settings
must suit the public API origin.

To restore the existing local HTTP listener:

```sh
export MOSAIC_GUI_SCHEME=http
unset MOSAIC_GUI_TLS_CERT_FILE MOSAIC_GUI_TLS_KEY_FILE
mosaic-gui
```

## Branding

Keep the organisation PNG outside public assets, preferably in the ignored
private-branding/ directory, or mount it separately in deployment. Its aspect
ratio is preserved. No organisation image is included in this repository.
When configured, the organisation logo appears at the left of the header,
followed by a subtle divider and MOSAIC branding. Without a configured logo,
neither the organisation image nor its divider is rendered. Account controls
remain together on the right.
The header, sign-in screen and SVG favicon share the same modular M tangram:
left lighter indigo #42549a; right darker indigo #16205d; pale inset pieces.
Bootstrap 5.3.8 CSS and the tangram are served locally. No CDN is needed.

## Behaviour

Sign-in checks the cookie and always opens an unsaved blank chat. A conversation
is created on the first non-empty message, not on login, refresh or clicking
New conversation. Existing empty conversations are retained; no history is deleted.
Dash builds the sidebar rows from conversation IDs. A browser callback fills
in titles and dates from the API response. Titles stay in the browser.
When a completed assistant response mentions Mermaid or contains a code fence,
its transcript text is sent
to a stateless Python Dash callback for diagram presentation. The callback receives
user and assistant text and a browser generation number. It keeps no server-side
transcript state and does not use or forward authentication credentials. Skills are grouped by the most-specific available
catalogue path and listed once. The Chat Skills panel starts collapsed. Open
the **Skills** tab to browse by domain and function or search the published
catalogue. Python Dash callbacks manage navigation, selections and save conflicts
from catalogue and workspace metadata. The browser executes paginated reads
and versioned saves directly with the API session cookie. Dash receives editor
state and display metadata for its callbacks. **Current Skills** tracks
your draft as you browse, and switching to Chat preserves both drafts.
Saved Skills that disappear from the published catalogue are marked
**Withdrawn** in **Current Skills**. They are excluded from the available
count and from new Goals. Remove them in the Skills Marketplace and save.
**Save Skills** replaces the saved selection, including an empty selection.
Changes apply to the next Goal. If another tab or an administrator saves first,
the Skills tab shows the latest saved Skills and keeps your draft for review.
Both side panels collapse to matching icon-only controls with accessible names
and tooltips; desktop separators support pointer and arrow-key
resizing. Markdown supports headings, lists, tables and highlighted code blocks.
Raw HTML is disabled; the resource policy blocks external embedded images.
Reasoning and raw tool/SDK metadata are not shown.

### Mermaid diagrams

MOSAIC answers can contain fenced `mermaid` blocks. Unlabelled fenced blocks
are also recognised when their first declaration is `flowchart` or `graph` with
a direction, `sequenceDiagram`, `classDiagram`, `stateDiagram`,
`stateDiagram-v2` or `erDiagram`. Leading blank lines and Mermaid comments are
allowed. Other language labels, ambiguous content, incomplete fences and unfenced
text remain unchanged. The GUI renders complete
blocks after the response finishes and when saved history is opened. Text keeps
streaming through the existing browser transport. The original response and
Mermaid syntax remain in the backend conversation history.

Each diagram fits the available panel space and has native Dash **−** (Zoom out),
**+** (Zoom in) and **Fit** buttons above the chart. Tooltips and accessibility
labels describe the symbol buttons. Each zoom step multiplies or divides the current
scale by 1.25, with no fixed zoom-in ceiling. **Fit** restores responsive sizing.
Enlarged diagrams scroll within
their own area, with scrollbars only when the chart exceeds the viewing area.
Each diagram has a **Source** disclosure and a **Copy** control. Copy
returns the original diagram text between the fence lines, including whitespace.
**Download SVG** saves the full rendered diagram at its original scale, including
parts outside the visible area when zoomed in.
Invalid diagrams retain both controls and show a fallback message. The underlying
component may also report a syntax error in the browser console. Per-diagram
configuration directives and interactive `click` commands are displayed as source.
Diagrams above the renderer's 50,000-character limit also retain source access.

Python splits the response and constructs the diagram cards using the
`dash-extensions` Mermaid component and native Dash controls. The library serves
its renderer locally. The existing browser controller supplies completed text and
rejects late render results after sign-out, conversation switches or newer messages.

Request failures display a safe message and, when supplied by the backend, a
UUID reference matching X-Correlation-ID. Include that reference when reporting
an issue. Missing or malformed references are omitted. Stream failures retain
the originating response reference; tokens and raw provider diagnostics remain hidden.

Chat submits text to the background job API and follows the job's event stream.
Native ADK partial text is incremental. Final aggregated text replaces the
partial turn, and chat reloads saved history after the job ends. After a dropped
stream, the browser tries once to reconnect from its last received event.
Closing the browser or signing out detaches the stream. Reopening the
conversation finds the latest job and reconnects if it is still active.
Stop requests cancellation and waits for the backend to finish. If the backend
cannot recover the conversation, the interrupted history stays readable and
its composer is disabled. Retrying a pending draft in the same page reuses
its submission key.

While a response is active, one temporary activity panel shows the most recent
observed tool operation and elapsed request time. Successful `load_skills` results
are matched to assigned workspace titles; multiple confirmed Skills appear in an
expandable list. Successful capability discovery provides approved operation
descriptions, used only for capabilities declared by those confirmed Skills.
Platform labels describe the semantic family (Kubernetes / OpenShift, OpenShift,
Splunk, MQ or Observability), not a discovered endpoint or hostname. Unknown or
unsafe metadata falls back to a generic operation label. Raw arguments, results,
instructions, addresses and thought signatures are never rendered in the panel.

The panel reads native ADK function-call and function-response shapes. The backend
forwards only allowlisted, redacted activity: operation names and correlation IDs,
confirmed Skill names and declared capability references, and available capability
descriptions. Other arguments, instructions, results, state and provider details
remain excluded. Both the GUI update and the backend activity-filter update are
required; a backend that forwards only answer text cannot supply tool progress.
There are no custom SSE event names or model narration. It never advances stages on
a timer. Parallel activity counts appear only when calls carry reliable IDs.
Without matching events or safe metadata, it remains generic. A ticking elapsed
timer measures waiting time, not backend liveness. The panel disappears and its
timer stops on completion, error, cancellation or sign-out. Reconnecting to an
active job can replay its activity, and saved chat history shows the messages.
A follow-up
that reuses Skills without another load event may have no selected-Skill label.
Real event timing depends on the installed ADA/ADK and any gateway buffering;
validate this against the target runtime. No reasoning summaries are inferred.

Sign-out clears the cookie through the backend and clears GUI user data. A
different token loads a different workspace. Stale responses from an earlier
sign-in cannot repopulate the UI. No token is placed in URLs, browser storage,
Dash stores or server callbacks; token entry uses a transient native input.
The GUI runs without debug mode or automatic reloading. In local testing, browser cookies
share a host across ports; in deployment the backend cookie remains host-only
on its separate HTTPS hostname. Never log or commit cookie values.

## Deployment

Host the GUI separately from the backend. Configure their sibling HTTPS origins
under the same parent domain, set the backend's exact GUI allowlist, and retain
secure backend cookies. The GUI needs no extra reverse-proxy routing to ADA.
The optional Dockerfile builds this folder only, listens on port 8050 and runs
as a non-root user. For direct TLS, provide the scheme and file-path environment
variables and mount the certificate/key read-only with permissions allowing that
user to read them. For hosting that terminates TLS upstream, leave the GUI's
listener in HTTP mode and omit the TLS file settings. DNS, certificate issuance,
renewal, hosting and deployed browser checks remain operator responsibilities.

## Tests

The Python tests require OpenSSL at /usr/bin/openssl and permission to
bind a loopback port. They generate disposable certificates in a temporary
directory, verify real HTTP/HTTPS listeners and worker shutdown, and reject
invalid TLS configuration. They do not install certificates into a trust store.

```sh
PYTHONPATH=src .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -q
node --test tests/test_adk_stream.mjs tests/test_api_client.mjs tests/test_invocation_activity.mjs tests/test_workspace_controller.mjs
```

BrowserFixtureBackend in tests/ is synthetic browser-QA data only. It is not
imported by the installed GUI and is not a fallback or demonstration mode in
the application. Browser checks against that fixture do not establish that
real ADA, provider execution or deployed cookie/CORS behaviour is working.
Complete functional testing against the actual backend before accepting the GUI.
