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

The MCP test uses the official SDK client with in-process ASGI transport. A separate
Python writer process commits Attribute, name, status, position, boon, and
ownership changes to the same disposable database. The existing companion reader
process keeps its warmed Evennia objects and Attribute caches; SDK calls must still
return current values and deny the former owner after transfer. A second account
can then read its newly owned character and participant Chronicle. Reader/writer
PIDs are checked as distinct. This proves process persistence freshness, while the
ASGI transport does not qualify a network, TLS, reverse proxy, or hosted OAuth flow.

Every outer subprocess has a 90-second timeout; writer children have 25 seconds;
HTTP result polling has a bounded two-second budget. A timeout kills and reaps the
direct child through `subprocess.run`. Writer children are independently bounded.
The writer role requires the temporary fixture marker and exact database filename.
The harness permits synchronous fixture/ORM operations in its private reactor
process only; it does not change production's async Django settings. A failing
assertion or request exits nonzero and the test includes its captured diagnostics.
