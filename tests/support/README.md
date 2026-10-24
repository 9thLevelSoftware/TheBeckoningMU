These integration checks create their own temporary SQLite databases, migrate only
those databases, and remove them when the subprocess exits. They never start the
live game, read a provider credential, or connect to a remote endpoint. The HTTP
provider credential is a fixed fixture value and its listener binds to an
OS-selected loopback port. The harness imports game settings but overrides its
database, provider, and log destinations before Django initializes.

From the repository root on Windows:

```powershell
.\.venv\Scripts\evennia.exe test --settings settings.py narrative.test_http_command mcp_server.test_process_freshness
```

The HTTP test executes `CmdHunt.parse()` and `func()` with real persisted Character
objects and the real hunting, dice-result, feeding, and resonance code. Only random
draws and the player message receiver are replaced. It covers opt-in and disabled
provider behavior, start, resume, repeated start, complete, opt-out, and the ordinary
deterministic hunt. Real Twisted Agent requests reach a local HTTP fixture. Delayed
responses allow another reactor callback to verify the request is still pending;
the test does not rely on machine-speed latency thresholds. Valid output, HTTP 503,
malformed JSON, an unauthorized citation, and attempted extra state output are
checked against unchanged deterministic outcomes and an exact dice draw count.
Stalled headers/bodies, chunked and declared size overflow, connection loss and a
late response also verify bounded terminal state and socket cancellation. The
original dice and Hunger result must appear once before provider traffic, and
remain readable after consent/provider disable without rerolling.

The MCP test uses the official SDK client against the production MCP application
on an owned, prebound OS-selected loopback HTTP socket. HTTPX disables environment
proxies and rejects requests outside that exact origin. Separate Python writer
processes commit Attribute, name, status, position, boon, and ownership changes to
the same disposable database. The existing reader process keeps its warmed
Evennia objects and Attribute caches; SDK calls must return current values and
deny the former owner after transfer. A second account can then read its newly
owned character and participant Chronicle. Another writer redacts a Chronicle
source through the actual moderation service. The same warmed SDK reader must
hide its generated recap, published correction and transitive descendant while
retaining successful generation history and derived prose for staff source
review. Reader/writer PIDs are checked as distinct. This qualifies local HTTP and
persistence freshness; TLS, reverse proxy and hosted OAuth remain separate gates.

Every outer subprocess has a 90-second timeout; writer children have 25 seconds;
HTTP result polling has a bounded two-second budget. A timeout kills and reaps the
direct child through `subprocess.run`. Writer children are independently bounded.
The writer role requires the temporary fixture marker and exact database filename.
The harness permits synchronous fixture/ORM operations in its private reactor
process only; it does not change production's async Django settings. A failing
assertion or request exits nonzero and the test includes its captured diagnostics.

For actual browser and game-session acceptance, the opt-in
`tests/support/completeness_e2e.py start` lease creates a separate temporary
database, Server/Portal, static host and fake provider on unique loopback ports.
It prints a manifest and remains alive for at most one hour. The `stop MANIFEST`
and `restart MANIFEST` commands request actions from the owning parent, which
only manages its own child handles. It never kills a PID read from a file.
`provider-mode MANIFEST success|failure|timeout` controls only the local fixture.
`game MANIFEST ROLE COMMANDS_JSON` uses an actual telnet session with a named
fixture account and records a transcript without its fixture login password.
Commands JSON is an array of objects with `command`, a required nonempty
`contains` assertion list, optional `excludes`, and bounded `wait`/`timeout`
values. Fixture account and current-character identity must both be confirmed.
Readiness uses exact loopback URLs without proxies or redirects. These harnesses are
optional development tools, not production services. Startup alone does not
count as completing the journeys in the acceptance plan.
