"""Opt-in local Server/Portal acceptance lease, isolated from the game database.

Run ``python tests/support/completeness_e2e.py start``. It prints a manifest path
after readiness and stays alive until its stop marker is requested (or one hour).
``... stop MANIFEST`` asks that owning process to stop its own children. It never
kills a PID from a file. Accounts use fixture-only passwords, not real accounts.
This harness prepares acceptance; successful startup is not journey completion.
"""

import argparse
import importlib.util
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "Acceptance-fixture-only-73!"
FORBIDDEN_PORTS = {6660, 6661, 6662, 6665, 6670, 5001}


class NoReadinessRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Readiness redirects are forbidden", headers, fp)


def loopback_ready(port):
    if type(port) is not int or not 0 < port < 65536 or port in FORBIDDEN_PORTS:
        raise ValueError("Readiness requires a leased loopback port")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoReadinessRedirect())
    url = f"http://127.0.0.1:{port}/"
    with opener.open(url, timeout=2) as response:
        return response.status == 200 and response.geturl() == url


def validate_game_steps(steps):
    if not isinstance(steps, list) or not steps:
        raise ValueError("Commands must be a nonempty JSON array")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each command step must be an object")
        command = step.get("command")
        if not isinstance(command, str) or not command.strip() or "\n" in command or "\r" in command:
            raise ValueError("One nonempty command per step required")
        expected, forbidden = step.get("contains"), step.get("excludes", [])
        if not isinstance(expected, list) or not expected or not isinstance(forbidden, list):
            raise ValueError("Each step needs at least one positive contains assertion")
        if any(not isinstance(value, str) or not value for value in expected + forbidden):
            raise ValueError("Assertions must be nonempty strings")
        quiet_wait, timeout = step.get("wait", 0.5), step.get("timeout", 10)
        if (
            type(quiet_wait) not in (int, float)
            or type(timeout) not in (int, float)
            or not 0.1 <= quiet_wait <= timeout <= 60
        ):
            raise ValueError("A step requires 0.1 <= wait <= timeout <= 60 seconds")


def confirm_fixture_identity(role, account_output, character_output):
    name = "Acceptance" + role
    if f"Account {name} (you are Out-of-Character)" not in account_output:
        raise AssertionError("Fixture account identity was not confirmed")
    if f"Character Sheet for: {name}" not in character_output:
        raise AssertionError("Fixture character puppeting was not confirmed")


SETTINGS_SOURCE = '''"""Generated disposable acceptance settings; no production fallback."""
import json
import os
from pathlib import Path
from server.conf.settings import *
_manifest_path = Path(os.environ["BECKONING_ACCEPTANCE_MANIFEST"]).resolve()
_run = _manifest_path.parent
_lease = json.loads(_manifest_path.read_text(encoding="utf-8"))
assert _run.name.startswith("beckoning-e2e-") and (_run / ".local-acceptance").is_file()
assert _lease["run_dir"] == str(_run) and _lease["database"] == str(_run / "acceptance.sqlite3")
_ports = _lease["ports"]
assert not set(_ports.values()) & {6660, 6661, 6662, 6665, 6670, 5001}
assert len(set(_ports.values())) == len(_ports)
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": _lease["database"]}}
SECRET_KEY = (_run / "fixture-secret").read_text(encoding="utf-8")
GAME_DIR = str(_run)
SERVERNAME = "Beckoning isolated acceptance"
LOG_DIR = str(_run)
SERVER_LOG_FILE = str(_run / "server.log")
PORTAL_LOG_FILE = str(_run / "portal.log")
HTTP_LOG_FILE = str(_run / "http.log")
LOCKWARNING_LOG_FILE = str(_run / "locks.log")
CACHE_DIR = str(_run / "cache")
MEDIA_ROOT = str(_run / "media")
STATIC_ROOT = str(_run / "static")
STATICFILES_DIRS = [str(Path(_lease["repository"]) / "web/static")]
TEMPLATES[0]["DIRS"] = [str(Path(base) / "web/templates" / suffix)
                         for base in (_lease["repository"], EVENNIA_DIR)
                         for suffix in ("", WEBSITE_TEMPLATE, WEBCLIENT_TEMPLATE)]
TELNET_PORTS = [_ports["telnet"]]
TELNET_INTERFACES = ["127.0.0.1"]
AMP_PORT = _ports["amp"]
AMP_HOST = AMP_INTERFACE = "127.0.0.1"
AMP_SERVER_PROTOCOL_CLASS = "acceptance_amp.LeasedAMPProtocol"
WEBSERVER_PORTS = [(_ports["web"], _ports["internal_web"])]
WEBSERVER_INTERFACES = ["127.0.0.1"]
WEBSOCKET_CLIENT_PORT = _ports["websocket"]
WEBSOCKET_CLIENT_INTERFACE = "127.0.0.1"
WEBSOCKET_CLIENT_URL = "ws://127.0.0.1:" + str(_ports["websocket"])
LOCKDOWN_MODE = True
SSL_ENABLED = SSH_ENABLED = IRC_ENABLED = RSS_ENABLED = False
GAME_INDEX_ENABLED = False
SERVER_SERVICES_PLUGIN_MODULES = []
PORTAL_SERVICES_PLUGIN_MODULES = []
NARRATIVE_AI = {"endpoint": "http://127.0.0.1:" + str(_ports["provider"]) + "/chat/completions",
                "model": "local-fixture", "api_key": "local-fixture-only",
                "request_timeout_seconds": 2, "connect_timeout_seconds": 1,
                "response_max_bytes": 4096, "prose_max_chars": 2000}
MCP_PUBLIC_URL = MCP_RESOURCE_URL = MCP_OAUTH_ISSUER = ""
PUBLIC_GAME_BASE_URL = "http://127.0.0.1:" + str(_ports["web"])
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = [PUBLIC_GAME_BASE_URL]
SESSION_COOKIE_NAME = "acceptance_session"
CSRF_COOKIE_NAME = "acceptance_csrf"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
MAX_NR_CHARACTERS = 10
TEST_ENVIRONMENT = False
DEFAULT_HOME = START_LOCATION = "#2"
'''

AMP_SOURCE = """from evennia.server.portal.amp_server import AMPServerProtocol
class LeasedAMPProtocol(AMPServerProtocol):
    def start_server(self, server_twistd_cmd):
        # Only the lease owner starts children, including restart qualification.
        raise RuntimeError("Acceptance server restart must be controlled by its lease")
"""


def manifest_at(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    run = path.parent
    if (
        path.name != "manifest.json"
        or not run.name.startswith("beckoning-e2e-")
        or not (run / ".local-acceptance").is_file()
        or data.get("run_dir") != str(run)
        or data.get("database") != str(run / "acceptance.sqlite3")
        or data.get("repository") != str(ROOT)
    ):
        raise ValueError("Not an acceptance lease for this checkout")
    return path, data


def initialize():
    """Populate only the explicitly bound disposable database before listeners."""
    manifest_at(os.environ["BECKONING_ACCEPTANCE_MANIFEST"])
    import django

    django.setup()
    import evennia
    from django.contrib.auth import get_user_model
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    evennia._init()
    from evennia.server import initial_setup
    from evennia.server.models import ServerConfig

    get_user_model().objects.create_superuser("AcceptanceOwner", "", PASSWORD)
    initial_setup.create_objects()
    ServerConfig.objects.conf("last_initial_setup_step", "done")
    call_command("collectstatic", interactive=False, verbosity=0)
    from traits.models import CharacterBio
    from world.seed_defaults import seed_defaults

    seed_defaults()
    roles = {"PlayerA": "Player", "PlayerB": "Player", "Builder": "Builder", "Admin": "Admin", "Harpy": "Harpy"}
    for name, permission in roles.items():
        account = evennia.create_account("Acceptance" + name, email=None, password=PASSWORD, permissions=[permission])
        assert not account.is_staff
        character = evennia.create_object(
            "typeclasses.characters.Character", key="Acceptance" + name, location="#2", home="#2"
        )
        CharacterBio.objects.create(character=character, account=account, status="approved")
        account.characters.add(character)
        character.clan = "Brujah"
        character.set_trait("Strength", 3)
        character.set_trait("Dexterity", 3)
        character.set_trait("Wits", 3)
        character.set_trait("Brawl", 3)
        character.set_trait("Athletics", 2)
        character.set_trait("Streetwise", 3)
        character.set_trait("Potence", 1, "disciplines")
        character.learn_power("Lethal Body")
        character.db.experience = {"total_earned": 100, "total_spent": 0, "log": []}
        character.hunger = 1
    npc = evennia.create_object("typeclasses.characters.Character", key="AcceptanceNPC", location="#2", home="#2")
    npc.splat = "mortal"
    from commands.v5.staff import NPC_LOCKS

    npc.locks.replace(NPC_LOCKS)
    path, data = manifest_at(os.environ["BECKONING_ACCEPTANCE_MANIFEST"])
    call_command("build_public_site_config", output=str(path.parent / "site-config.js"), verbosity=0)
    print(json.dumps({"initialized": data["database"]}), flush=True)


def serve_static():
    manifest, data = manifest_at(os.environ["BECKONING_ACCEPTANCE_MANIFEST"])

    class StaticHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "web/website/VampSite"), **kwargs)

        def do_GET(self):  # noqa: N802
            if self.path.split("?", 1)[0] == "/assets/js/site-config.js":
                content = (manifest.parent / "site-config.js").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            super().do_GET()

    ThreadingHTTPServer(("127.0.0.1", data["ports"]["static"]), StaticHandler).serve_forever()


def serve_provider():
    """Local fixture response only; never store player prompts or tokens."""
    manifest, data = manifest_at(os.environ["BECKONING_ACCEPTANCE_MANIFEST"])

    class ProviderHandler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path != "/chat/completions":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 1048576:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
            mode = (manifest.parent / "provider-mode").read_text(encoding="utf-8").strip()
            if mode == "timeout":
                time.sleep(3)
            citations = []
            for message in payload.get("messages", []):
                content = message.get("content", "")
                if "Sources: " in content:
                    citations = [str(source["id"]) for source in json.loads(content.split("Sources: ", 1)[1])]
            response = {
                "prose": "The local fixture scene remains quiet. No mechanical outcome is changed.",
                "citations": citations,
            }
            body = json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()
            try:
                self.send_response(503 if mode == "failure" else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            print(json.dumps({"fixture_provider_mode": mode, "citation_count": len(citations)}), flush=True)

    ThreadingHTTPServer(("127.0.0.1", data["ports"]["provider"]), ProviderHandler).serve_forever()


def stop_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def game_session(manifest_path, role, commands_path):
    """Run actual telnet commands using only a named disposable fixture account."""
    import re
    import telnetlib

    manifest, data = manifest_at(manifest_path)
    if data["state"] != "ready" or role not in ("PlayerA", "PlayerB", "Builder", "Admin", "Harpy"):
        raise ValueError("A ready lease and fixture role are required")
    steps = json.loads(Path(commands_path).read_text(encoding="utf-8"))
    validate_game_steps(steps)
    transcript = []
    path = manifest.parent / ("transcript-" + role + "-" + str(time.time_ns()) + ".json")
    with telnetlib.Telnet("127.0.0.1", data["ports"]["telnet"], timeout=5) as connection:

        def read_until_quiet(minimum=0.5, maximum=5):
            output = b""
            deadline, quiet = time.monotonic() + maximum, time.monotonic() + minimum
            while time.monotonic() < deadline:
                chunk = connection.read_very_eager()
                if chunk:
                    output += chunk
                    quiet = time.monotonic() + minimum
                elif time.monotonic() >= quiet:
                    break
                time.sleep(0.05)
            return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output.decode("utf-8", errors="replace"))

        read_until_quiet()
        connection.write(f"connect Acceptance{role} {PASSWORD}\n".encode())
        read_until_quiet()
        connection.write(b"ooc\n")
        read_until_quiet()
        connection.write(b"look\n")
        account_output = read_until_quiet()
        connection.write(f"ic Acceptance{role}\n".encode())
        read_until_quiet()
        # +sheet without a target reports this session's own character. An
        # account-wide sessions list could contain a different session's puppet.
        connection.write(b"+sheet\n")
        character_output = read_until_quiet()
        confirm_fixture_identity(role, account_output, character_output)
        transcript.append({"fixture": role, "identity_confirmed": True})
        for step in steps:
            command = step["command"]
            quiet_wait, timeout = step.get("wait", 0.5), step.get("timeout", 10)
            connection.write((command + "\n").encode())
            output = read_until_quiet(minimum=quiet_wait, maximum=timeout)
            transcript.append({"command": command, "output": output})
            # Keep completed steps even when a later assertion fails, so an
            # affected retry does not replay earlier economic/game mutations.
            path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
            for expected in step.get("contains", []):
                if expected not in output:
                    raise AssertionError(
                        json.dumps({"command": command, "missing": expected, "output": output, "transcript": str(path)})
                    )
            for forbidden in step.get("excludes", []):
                if forbidden in output:
                    raise AssertionError(json.dumps({"command": command, "unexpected": forbidden, "output": output}))
    path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    print(json.dumps({"transcript": str(path), "steps": len(steps), "passed": True}), flush=True)


def start():
    run = Path(tempfile.mkdtemp(prefix="beckoning-e2e-"))
    (run / ".local-acceptance").touch()
    (run / "server/conf").mkdir(parents=True)
    (run / "server/conf/settings.py").write_text("# Acceptance game directory marker.\n", encoding="utf-8")
    sockets = []
    ports = {}
    for name in ("web", "internal_web", "telnet", "amp", "websocket", "static", "provider"):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sockets.append(sock)
        ports[name] = sock.getsockname()[1]
    assert not set(ports.values()) & FORBIDDEN_PORTS
    manifest = run / "manifest.json"
    data = {
        "run_dir": str(run),
        "repository": str(ROOT),
        "database": str(run / "acceptance.sqlite3"),
        "ports": ports,
        "owner_pid": os.getpid(),
        "children": {},
        "state": "preparing",
    }
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    (run / "fixture-secret").write_text(secrets.token_urlsafe(64), encoding="utf-8")
    (run / "acceptance_settings.py").write_text(SETTINGS_SOURCE, encoding="utf-8")
    (run / "acceptance_amp.py").write_text(AMP_SOURCE, encoding="utf-8")
    (run / "provider-mode").write_text("success", encoding="utf-8")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "acceptance_settings",
        "BECKONING_ACCEPTANCE_MANIFEST": str(manifest),
        "PYTHONPATH": os.pathsep.join((str(run), str(ROOT))),
        "PYTHONUNBUFFERED": "1",
    }
    children, logs = [], []
    try:
        with (run / "initialize.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [sys.executable, __file__, "initialize"],
                cwd=run,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=True,
            )
        for sock in sockets:
            sock.close()
        package = Path(importlib.util.find_spec("evennia").origin).parent
        commands = {
            "portal": [
                sys.executable,
                "-c",
                "from twisted.scripts.twistd import run; run()",
                "--nodaemon",
                "--python=" + str(package / "server/portal/portal.py"),
            ],
            "server": [
                sys.executable,
                "-c",
                "from twisted.scripts.twistd import run; run()",
                "--nodaemon",
                "--python=" + str(package / "server/server.py"),
            ],
            "static": [sys.executable, __file__, "static"],
            "provider": [sys.executable, __file__, "provider"],
        }
        current = {}

        def launch(role):
            log = (run / (role + "-process.log")).open("a", encoding="utf-8")
            logs.append(log)
            child = subprocess.Popen(
                commands[role],
                cwd=run,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            children.append(child)
            current[role] = child
            data["children"][role] = child.pid

        for role in commands:
            launch(role)
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Acceptance child exited; inspect " + str(run))
            try:
                if loopback_ready(ports["web"]):
                    break
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.25)
        else:
            raise TimeoutError("Acceptance readiness deadline exceeded: " + str(run))
        data["state"] = "ready"
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(json.dumps({"manifest": str(manifest), "state": "ready", "ports": ports}), flush=True)
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline and not (run / "stop-requested").exists():
            restart = run / "restart-requested"
            if restart.exists():
                restart.unlink()
                data["state"] = "restarting"
                manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                stop_child(current["server"])
                launch("server")
                # The Portal remains owned by the same lease. Only its Server restarts.
                ready_by = time.monotonic() + 60
                while time.monotonic() < ready_by:
                    if current["server"].poll() is not None:
                        raise RuntimeError("Acceptance restarted Server exited")
                    try:
                        if loopback_ready(ports["internal_web"]):
                            break
                    except (urllib.error.URLError, TimeoutError):
                        pass
                    time.sleep(0.25)
                else:
                    raise TimeoutError("Acceptance restart readiness deadline exceeded")
                data["restart_count"] = data.get("restart_count", 0) + 1
                data["state"] = "ready"
                manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                print(json.dumps({"manifest": str(manifest), "restart_count": data["restart_count"]}), flush=True)
            if any(child.poll() is not None for child in current.values()):
                raise RuntimeError("Acceptance child exited; inspect " + str(run))
            time.sleep(0.5)
    finally:
        for sock in sockets:
            sock.close()
        for child in reversed(children):
            stop_child(child)
        for log in logs:
            log.close()
        data["state"] = "stopped"
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(json.dumps({"manifest": str(manifest), "state": "stopped"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("start", "stop", "restart", "initialize", "static", "provider", "provider-mode", "game")
    )
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("value", nargs="?")
    parser.add_argument("commands", nargs="?")
    args = parser.parse_args()
    if args.mode == "stop":
        manifest, _data = manifest_at(args.manifest)
        (manifest.parent / "stop-requested").touch()
    elif args.mode == "initialize":
        initialize()
    elif args.mode == "static":
        serve_static()
    elif args.mode == "provider":
        serve_provider()
    elif args.mode == "provider-mode":
        manifest, _data = manifest_at(args.manifest)
        if args.value not in ("success", "failure", "timeout"):
            raise ValueError("Unknown fixture provider mode")
        (manifest.parent / "provider-mode").write_text(args.value, encoding="utf-8")
    elif args.mode == "restart":
        manifest, data = manifest_at(args.manifest)
        if data["state"] != "ready":
            raise ValueError("Only a ready lease can restart")
        (manifest.parent / "restart-requested").touch()
    elif args.mode == "game":
        game_session(args.manifest, args.value, args.commands)
    else:
        start()


if __name__ == "__main__":
    main()
