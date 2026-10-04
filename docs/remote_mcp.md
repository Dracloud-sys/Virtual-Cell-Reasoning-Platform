# Remote MCP: the same tools behind a URL, for one person

A Claude **custom connector** ("Add custom connector → Remote MCP server URL") reaches its
server from Anthropic's cloud, not from the user's machine. The stdio server in `.mcp.json`
cannot serve that, so `python -m virtualcell.mcp --transport streamable-http` serves **the
same `build_server()` and the same six tools** over Streamable HTTP, behind OAuth, for one
configured person.

**Nothing is deployed.** No HTTPS address exists yet. This document is the procedure, and
the table below says which parts of it have run.

## What has and has not run

| stage | status |
|---|---|
| in-process: discovery, 401/403, every token refusal, `initialize` / `list_tools` / `call_tool`, two searches read and checked, restart | **done** — `tests/integration/test_mcp_remote.py` |
| real local HTTP: uvicorn on loopback + the SDK's own streamable-HTTP client | **done** — same file |
| stdio unchanged: the committed command spawned as a host spawns it | **done** — same file, plus the existing `test_mcp_server.py` |
| image: `docker/mcp.Dockerfile` built and run locally | **done** once, in a sandbox — see [Image](#image) |
| real Auth0 login and a real Auth0-issued token accepted | **not run** — needs the account below |
| public HTTPS deployment on Render | **not run** — needs the account below |
| registered as a Claude custom connector, login completed, a tool called | **not run** — needs both of the above |

The tests sign their own tokens with a key they generate. That proves the verifier refuses
what it must and accepts a correctly formed token; it does not prove that Auth0, configured as
below, issues one. Only the first real login shows that.

## Shape

```
Claude (Anthropic cloud)
  │ POST /mcp, no token
  ├──────────────▶ 401  WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"
  │ GET that metadata
  ├──────────────▶ {"resource": "<exact /mcp URL>", "authorization_servers": ["<Auth0 issuer>"], "scopes_supported": ["vcrp:use"]}
  │ GET <issuer>/.well-known/oauth-authorization-server         (Auth0 serves this)
  │ browser: /authorize (PKCE S256, resource=<URL>, scope=vcrp:use)  → user logs in at Auth0
  │ /oauth/token with the pre-registered client id + secret      → RS256 JWT access token
  │ POST /mcp, Authorization: Bearer <JWT>
  └──────────────▶ verified here → build_server()'s six tools
```

This server is a **resource server only**. It holds no user credentials, runs no login page,
and registers no clients. Auth0 does all of that.

## What a request must carry

Every request to `/mcp` is checked, in this order; any failure is a `401` (or `403` for scope)
that points back at the metadata, never a degraded answer:

1. a `Bearer` token that is a JWT signed **RS256** by a key in the issuer's published key set
   (`<issuer>.well-known/jwks.json`; an unreachable key set refuses, it does not trust);
2. `iss` equal to `VCRP_MCP_OAUTH_ISSUER` **exactly** — Auth0's issuer ends in `/`;
3. `aud` containing `VCRP_MCP_RESOURCE_URL` exactly;
4. `exp` present and in the future; `sub` present;
5. `sub` equal to `VCRP_MCP_ALLOWED_SUBJECT` — **one person**. A valid token for anyone else in
   the same tenant is refused;
6. every scope in `VCRP_MCP_REQUIRED_SCOPES` present in the `scope` claim (else `403`).

The Host header is checked against the resource URL's host (`421` otherwise). That is protection
against DNS rebinding, **not identity** — the right host with no token is still `401`. The
transport is stateless, so there is no session id, and nothing could treat one as identity.

## Settings

| variable | required | meaning |
|---|---|---|
| `VCRP_MCP_RESOURCE_URL` | yes | the exact URL registered in Claude, ending in `/mcp`, e.g. `https://<service>.onrender.com/mcp`. It is also the Auth0 API identifier, the token audience and the metadata `resource`. No trailing slash |
| `VCRP_MCP_OAUTH_ISSUER` | yes | the `issuer` value from `https://<tenant>.auth0.com/.well-known/openid-configuration`, copied exactly (`https://<tenant>.<region>.auth0.com/`, with the trailing slash) |
| `VCRP_MCP_ALLOWED_SUBJECT` | yes | the Auth0 `user_id` of the one person, e.g. `auth0|6...` or `google-oauth2|1...` |
| `VCRP_MCP_REQUIRED_SCOPES` | yes | `vcrp:use` (space- or comma-separated if more) |
| `VCRP_MCP_JWKS_URL` | no | defaults to `<issuer>.well-known/jwks.json` |
| `VCRP_MCP_HOST` | no | bind address; `127.0.0.1` by default, `0.0.0.0` in the image |
| `PORT` | no | set by Render (10000); `8000` by default |
| `VIRTUALCELL_MCP_LITERATURE` | no | the image passes `--literature` already |

**Any of the four required settings missing or malformed: the process prints every problem and
exits with status 2 before binding a port.** An HTTP server that started without them would
serve the tools to anyone. A plain-`http` URL is refused except on a loopback address.

## One process, one worker — and what a restart loses

`research_payloads.IssuedEvidence` (what this server issued, used to classify `server_retrieved`
vs `host_supplied`) and the fetched-body cache live **in the process**. A second worker or
instance would each hold a different record. So the image runs **one process with one worker**,
`uvicorn.run(..., workers=1)`, and a Free Render service cannot scale beyond one instance anyway.

A Free Render service **spins down after 15 minutes without traffic and may restart at any
time**; a redeploy restarts it too. Every restart empties the record. That is handled, not
hidden:

- `read_evidence_source` on an id issued before the restart returns `status: not_issued`, whose
  detail says to call `research_evidence` again;
- `check_research_draft` classifies such an item as `host_supplied` — the new process did not
  issue it and will not vouch for it;
- ids are content-derived, so **running the same search again re-issues the same id**, after
  which reads work and the check says `server_retrieved` again.

**Recovery procedure after a restart:** re-run the `research_evidence` search that produced the
ids you are citing (same question, `search_literature: true`), confirm the ids you cite came
back, then continue reading and re-run `check_research_draft`. Do not relabel a
`host_supplied` result as retrieved; re-retrieve it. Pinned by
`test_a_restart_loses_the_record_and_says_so_then_a_new_search_restores_it`.

No Redis, database or disk is added for this, and no keep-alive pinger: both would cost money
or free-plan hours, and the recovery above is cheap.

**Finding, not fixed here:** the record is per *process*, not per user. With exactly one
allowed subject that is the same thing. Before a second person is ever allowed, the record has
to be isolated per subject — otherwise one person's retrieval would count as `server_retrieved`
for another. The refusal text also says "in this session", which over stateless HTTP means
"since this process started".

## Zero-cost operation: what the free plans allow and where they stop

Checked against the providers' documentation on 2026-09-25. Each console may differ; **if any
step below asks for a card or a paid feature, stop and report it — do not work around it.**

**Render, Free web service** ([render.com/docs/free](https://render.com/docs/free))

- 0.1 CPU, 512 MB RAM. The image idles at about 57 MiB, measured locally.
- `https://<name>.onrender.com` with managed TLS — no domain purchase, no proxy.
- Spins down after 15 minutes idle; spin-up takes about a minute. Restarts may happen at any
  time. The filesystem is ephemeral. One instance only.
- 750 free instance-hours per workspace per month; when exhausted, Free services are
  **suspended** until the next month — not billed.
- Outbound bandwidth over the included amount is **billed only if a payment method is on
  file; without one, Free services are suspended instead.** So: **do not add a payment
  method.** Suspension is the intended failure mode.
- Render says Free services are not for production. This is one person's research tool.

**Auth0 Free** — every piece used here is a basic feature: one API, one Regular Web
Application, one database user, tenant Default Audience. The **Resource Parameter
Compatibility Profile** toggle's plan availability is not stated in Auth0's documentation; the
Default Audience setting below makes the flow work without it. No Actions, no custom domain, no
paid add-on. **Keep Dynamic Client Registration off**; the pre-registered client is used.

**Claude** — custom connectors are available on Free (limited to one custom connector), Pro,
Max, Team and Enterprise.

### Cold start versus Claude's 10-second discovery timeout

Claude waits **10 seconds** for OAuth discovery responses. A sleeping Free service takes about
a minute to wake. So the first contact after idle can fail even when everything is configured
correctly. Before connecting — or when a call fails after a quiet spell — open
`https://<service>.onrender.com/.well-known/oauth-protected-resource/mcp` in a browser, wait for
the JSON, then connect or retry. That is a manual step on purpose; an automated keep-alive would
spend free hours around the clock.

## Setup — what the user does, in order

The server URL has to exist before Auth0 can be told it, and the service refuses to start until
Auth0's values are in it. So the order is: create the Render service (its first start fails,
safely), configure Auth0, set the variables, deploy by hand.

### 1. Render — create the service (no card)

1. Sign in to Render with GitHub; Hobby / free workspace. **Do not add a payment method.**
2. **New → Web Service** → this repository → branch **`feat/research-path`**.
3. Runtime **Docker**; Dockerfile path **`docker/mcp.Dockerfile`**; Docker context `.`.
4. Instance type **Free**. Region: any.
5. **Auto-Deploy: Off** (Settings → Build & Deploy → Auto-Deploy → *Off*). Deploys happen only
   when you press *Manual Deploy*.
6. Leave the variables empty for now and create the service. Note its URL,
   `https://<name>.onrender.com`. The first deploy will **fail on purpose**: the log shows
   `refusing to serve over HTTP: ... is not set. Nothing was started.`

`VCRP_MCP_RESOURCE_URL` is that URL plus `/mcp`, exactly.

### 2. Auth0 — tenant, API, application, one user (Free)

1. Sign up, create a tenant. Open `https://<tenant>.<region>.auth0.com/.well-known/openid-configuration`
   and copy `issuer` exactly → `VCRP_MCP_OAUTH_ISSUER`.
2. **Applications → APIs → Create API**
   - Identifier: **`https://<name>.onrender.com/mcp`** — the resource URL, exactly, no slash.
   - Signing algorithm **RS256**.
   - Permissions tab: add **`vcrp:use`**.
   - Settings: *Allow Offline Access* **on** (Claude asks for `offline_access` to refresh
     instead of logging in again daily). RBAC can stay off.
3. **Settings → General → API Authorization Settings → Default Audience**: set it to the same
   `https://<name>.onrender.com/mcp`. This makes Auth0 issue a JWT for this API even if it
   ignores the `resource` parameter Claude sends. If **Settings → Advanced → Resource Parameter
   Compatibility Profile** is available on your plan, turn it on as well.
4. **Applications → Create Application → Regular Web Application**
   - Allowed Callback URLs: **`https://claude.ai/api/mcp/auth_callback`**
   - Grant types (Advanced settings): **Authorization Code** and **Refresh Token**.
   - Credentials: authentication method **Client Secret (Post)**; if the token exchange fails
     with `invalid_client`, switch to **Client Secret (Basic)**.
   - Copy the **Client ID** and **Client Secret** — they go into Claude, not into Render.
5. **Authentication → Database → Username-Password-Authentication → Disable Sign Ups: on.**
   Then **User Management → Users → Create User** for yourself (or use a social connection).
   Copy the user's **user_id** → `VCRP_MCP_ALLOWED_SUBJECT`.

### 3. Render — set the variables and deploy by hand

Environment → add:

```
VCRP_MCP_RESOURCE_URL     = https://<name>.onrender.com/mcp
VCRP_MCP_OAUTH_ISSUER     = https://<tenant>.<region>.auth0.com/
VCRP_MCP_ALLOWED_SUBJECT  = auth0|<your user id>
VCRP_MCP_REQUIRED_SCOPES  = vcrp:use
```

Then **Manual Deploy → Deploy latest commit**. The log should end with uvicorn listening.

### 4. Check the address before involving Claude

```
curl -s https://<name>.onrender.com/.well-known/oauth-protected-resource/mcp
#  → "resource" is exactly https://<name>.onrender.com/mcp
#    "authorization_servers" is exactly [ your issuer ]
curl -si -X POST https://<name>.onrender.com/mcp -H 'content-type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i -E '^HTTP|www-authenticate'
#  → 401 with resource_metadata="https://<name>.onrender.com/.well-known/oauth-protected-resource/mcp"
```

### 5. Claude — add the connector

Wake the service first (above). Then **Customize → Connectors → + → Add custom connector**:

- URL: `https://<name>.onrender.com/mcp`
- **Advanced settings**: OAuth Client ID and Client Secret from step 2.4.

Claude opens Auth0's login; sign in as the one allowed user. Then ask for something that calls a
tool — `list_domains` is the cheapest; `research_evidence` with `search_literature: true`
exercises Europe PMC.

### Reading a failure

| symptom | likely cause |
|---|---|
| "Couldn't reach the MCP server" right after idle | cold start beyond the 10 s discovery wait — wake it, retry |
| login succeeds, every call `401`; log `refused a token: InvalidAudienceError` | token not issued for this API: Default Audience / API identifier ≠ resource URL exactly |
| log `InvalidIssuerError` | `VCRP_MCP_OAUTH_ISSUER` not copied exactly (trailing slash) |
| log `refused a valid token for a subject this server does not serve` | signed in as someone other than `VCRP_MCP_ALLOWED_SUBJECT` — working as intended |
| log `DecodeError` | an opaque (non-JWT) token: no audience was applied — see Default Audience |
| `403 insufficient_scope` | token lacks `vcrp:use`: check the API's permission and that Claude requested it |
| `421` | the Host does not match `VCRP_MCP_RESOURCE_URL` — a URL typo |

The server logs the reason class, never the token.

## Image

`docker/mcp.Dockerfile`: Python 3.12 slim, `pip install ".[mcp-http]"` (no `[llm]`, no
generation API key), a non-root user (`uid 10001`), `VCRP_MCP_HOST=0.0.0.0`, `PORT=10000`,
`CMD python -m virtualcell.mcp --literature --transport streamable-http`. The REST API image,
`docker/Dockerfile`, is unchanged.

Measured once, locally: with no settings the container exits `2` before binding; configured, it
runs as `uid 10001` with a single server process, answers the metadata and the `401` in about
two seconds from start, and idles at about 57 MiB. The sandbox that built it intercepts TLS, so
the build there used a copy of this Dockerfile that additionally trusted the sandbox's proxy CA;
the committed file needs no such step on Render.

## Blueprint (reference only)

The dashboard steps above are the supported path. If a Blueprint is ever preferred, this is the
equivalent. It is kept here rather than as `render.yaml` at the root, so that connecting the
repository never creates anything by itself.

```yaml
services:
  - type: web
    name: vcrp-mcp
    runtime: docker
    plan: free
    branch: feat/research-path
    dockerfilePath: ./docker/mcp.Dockerfile
    dockerContext: .
    autoDeployTrigger: off
    envVars:
      - key: VCRP_MCP_RESOURCE_URL
        sync: false
      - key: VCRP_MCP_OAUTH_ISSUER
        sync: false
      - key: VCRP_MCP_ALLOWED_SUBJECT
        sync: false
      - key: VCRP_MCP_REQUIRED_SCOPES
        value: vcrp:use
```

## Sources

- Claude connector authentication — discovery, PKCE S256, scopes, callback URL, 10 s limit, egress range:
  <https://claude.com/docs/connectors/building/authentication>
- Claude custom connectors — plans, the Advanced settings client ID/secret:
  <https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp>
- Render Free limits: <https://render.com/docs/free>; `PORT`, `0.0.0.0`, onrender.com TLS:
  <https://render.com/docs/web-services>; Blueprint fields: <https://render.com/docs/blueprint-spec>
- Auth0 Resource Parameter Compatibility Profile:
  <https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile>
- Auth0 authorization server metadata (RFC 8414 path served, S256 advertised) was read from a
  public Auth0 tenant's `/.well-known/oauth-authorization-server` on 2026-09-25.
