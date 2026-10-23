"""Disposable-process acceptance harness; never connects to the game database.

Run through narrative.test_http_command or mcp_server.test_process_freshness.
Each top-level invocation creates a fresh SQLite database under TemporaryDirectory.
The writer role is only accepted with the parent's fixture marker and exact filename.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def bootstrap(database):
    database = Path(database).resolve()
    assert database.name == "acceptance.sqlite3" and (database.parent / ".local-acceptance").is_file()
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    from django.conf import settings

    from server.conf import settings as game_settings

    config = {name: getattr(game_settings, name) for name in dir(game_settings) if name.isupper()}
    config.update(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(database)}},
        NARRATIVE_AI={},
        TEST_ENVIRONMENT=True,
        SERVER_LOG_FILE=str(database.parent / "server.log"),
        PORTAL_LOG_FILE=str(database.parent / "portal.log"),
        LOCKDOWN_MODE=True,
    )
    settings.configure(**config)
    import django

    django.setup()


def initialize():
    import evennia
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    evennia._init()


def fixtures():
    import evennia

    accounts = [
        evennia.create_account(f"LocalAccount{index}", email=None, password="local-fixture-only") for index in (1, 2)
    ]
    characters = []
    for index, account in enumerate(accounts, 1):
        character = evennia.create_object("typeclasses.characters.Character", key=f"LocalCharacter{index}", nohome=True)
        character.account = account
        character.db.stats = {
            "attributes": {"mental": {"wits": 4}},
            "skills": {"social": {"streetwise": 3}, "physical": {"stealth": 3}},
        }
        character.db.vampire = {"hunger": 5, "clan": "Brujah", "predator_type": "Alleycat"}
        characters.append(character)
    return accounts, characters


def narrative_http():
    from django.conf import settings
    from twisted.internet import defer, reactor, task
    from twisted.web.resource import Resource
    from twisted.web.server import NOT_DONE_YET, Site

    from commands.v5.hunt import CmdHunt
    from commands.v5.utils.blood_utils import get_hunger
    from narrative.models import NarrativeConsent, StoryGenerationRequest, StorySession

    _accounts, (character, _other) = fixtures()
    character.msg = Mock()

    def command(arguments):
        command = CmdHunt()
        command.caller = character
        command.args = arguments
        command.cmdstring = "+hunt"
        command.raw_string = "+hunt" + arguments
        command.obj = character
        command.parse()
        command.func()

    class Endpoint(Resource):
        isLeaf = True  # noqa: N815

        def __init__(self):
            super().__init__()
            self.mode = "valid"
            self.received = []
            self.heartbeats = []

        def render_POST(self, request):  # noqa: N802
            payload = json.loads(request.content.read())
            assert request.path == b"/chat/completions"
            assert request.getHeader("Authorization") == "Bearer local-fixture-only"
            self.received.append(payload)
            pending = StoryGenerationRequest.objects.latest("id")
            assert pending.status == "pending" and pending.action_text
            mode = self.mode

            def heartbeat():
                assert StoryGenerationRequest.objects.get(pk=pending.pk).status == "pending"
                self.heartbeats.append(pending.pk)

            def respond():
                request.setHeader(b"Content-Type", b"application/json")
                content = {"prose": "A local shadow moves. |r", "citations": []}
                if mode == "citation":
                    content["citations"] = ["unauthorized-fact"]
                if mode == "mutation":
                    content["hunger"] = 0
                body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
                if mode == "http-error":
                    request.setResponseCode(503)
                elif mode == "malformed":
                    body = b"{not-json"
                request.write(body)
                request.finish()

            reactor.callLater(0.02, heartbeat)
            reactor.callLater(0.15, respond)
            return NOT_DONE_YET

    endpoint = Endpoint()
    listener = reactor.listenTCP(0, Site(endpoint), interface="127.0.0.1")

    @defer.inlineCallbacks
    def wait_for_request():
        def ready():
            request = StoryGenerationRequest.objects.latest("id")
            return request if request.status != "pending" else None

        for _attempt in range(200):
            request = ready()
            if request is not None:
                return request
            yield task.deferLater(reactor, 0.01, lambda: None)
        raise AssertionError("Local HTTP request did not finish within its bounded wait")

    @defer.inlineCallbacks
    def exercise(_reactor):
        try:
            command("/story start street")
            assert "opt-in" in str(character.msg.call_args)
            command("/story opt-in")
            assert NarrativeConsent.objects.get(character=character).opted_in
            for action in ("start street", "resume I wait.", "complete"):
                command("/story " + action)
            assert StorySession.objects.count() == StoryGenerationRequest.objects.count() == 0
            assert get_hunger(character) == 5
            settings.NARRATIVE_AI = {
                "endpoint": f"http://127.0.0.1:{listener.getHost().port}/chat/completions",
                "model": "local-fixture",
                "api_key": "local-fixture-only",
            }
            with (
                patch("dice.dice_roller.randint", return_value=8) as dice,
                patch("commands.v5.utils.hunting_utils.random.randint", return_value=100),
                patch("commands.v5.utils.hunting_utils.random.choices", return_value=["Sanguine"]),
                patch("commands.v5.utils.hunting_utils.random.choice", side_effect=lambda values: values[0]),
            ):
                command("/story start street")
                session = StorySession.objects.get(character=character, status="active")
                outcome = dict(session.deterministic_outcome)
                assert outcome["hunger_before"] == 5 and outcome["hunger_after"] == 2
                assert get_hunger(character) == 2 and dice.call_count == 8, (get_hunger(character), dice.call_count)
                first = yield wait_for_request()
                assert first.status == "succeeded" and first.action_text == ""
                assert first.response == "A local shadow moves. |r"
                assert "||r" in str(character.msg.call_args)
                for mode in ("valid", "http-error", "malformed", "citation", "mutation"):
                    endpoint.mode = mode
                    command("/story resume I watch from the doorway.")
                    request = yield wait_for_request()
                    assert request.status == ("succeeded" if mode == "valid" else "failed"), mode
                    assert request.action_text == ""
                    assert (bool(request.response)) == (mode == "valid")
                    session.refresh_from_db()
                    assert session.deterministic_outcome == outcome
                    assert get_hunger(character) == 2 and dice.call_count == 8
                assert "A local shadow moves." in endpoint.received[1]["messages"][-1]["content"]
                command("/story start street")  # existing session must not resolve a second hunt
                yield wait_for_request()
                assert dice.call_count == 8 and StorySession.objects.count() == 1
                command("/story complete")
                session.refresh_from_db()
                assert session.status == "completed" and session.current_action == ""
                assert not session.requests.exclude(action_text="").exists()
                command("/story opt-out")
                assert not NarrativeConsent.objects.get(character=character).opted_in
                # Ordinary deterministic hunting continues to work without any provider.
                settings.NARRATIVE_AI = {}
                command(" street")
                assert dice.call_count == 16 and get_hunger(character) == 0
                assert StoryGenerationRequest.objects.count() == 7
            assert len(endpoint.received) == len(endpoint.heartbeats) == 7
            print(json.dumps({"gate": "command-http", "requests": 7, "heartbeats_while_pending": 7, "passed": True}))
        finally:
            yield listener.stopListening()

    task.react(exercise)


def write_fixture(database, phase):
    import evennia
    from evennia.objects.models import ObjectDB

    evennia._init()
    from boons.models import BoonLedger
    from chronicle.models import ChronicleEvent
    from status.models import CamarillaPosition, CharacterStatus

    character = ObjectDB.objects.get(db_key="LocalCharacter1" if phase == "update" else "Persisted new name")
    if phase == "update":
        character.db.stats = {"skills": {"stealth": 4}}
        character.db.vampire = {"hunger": 2}
        character.db.pools = {"health": 7}
        character.db.advantages = {"merits": ["Current merit"]}
        ObjectDB.objects.filter(pk=character.pk).update(db_key="Persisted new name")
        CharacterStatus.objects.filter(character=character).update(earned_status=3, position_status=1)
        CamarillaPosition.objects.update(name="Persisted new position")
        BoonLedger.objects.filter(character=character).update(total_debt_weight=5, total_credit_weight=8, net_weight=3)
    else:
        from evennia.accounts.models import AccountDB

        owner = AccountDB.objects.get(username="LocalAccount2")
        ObjectDB.objects.filter(pk=character.pk).update(db_account_id=owner.pk)
        ChronicleEvent.objects.filter(idempotency_key="local-private").update(summary="Fresh private event")
    print(json.dumps({"writer_pid": os.getpid(), "phase": phase}))


def mcp_freshness(database):
    from datetime import timedelta

    import httpx
    from asgiref.sync import async_to_sync
    from django.conf import settings
    from django.utils import timezone
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from oauth2_provider.models import AccessToken, Application

    from boons.models import BoonLedger
    from chronicle.models import ChronicleEvent
    from mcp_server.app import create_application
    from mcp_server.auth import OAUTH_SCOPES
    from status.models import CamarillaPosition, CharacterStatus

    (account, account2), (character, foreign) = fixtures()
    character.db.pools = {"health": 1}
    character.db.advantages = {"merits": ["Old merit"]}
    cached_stats = character.db.stats
    cached_name = character.key
    position = CamarillaPosition.objects.create(name="Old position")
    status = CharacterStatus.objects.create(character=character, earned_status=1, position=position)
    ledger = BoonLedger.objects.create(character=character, total_debt_weight=1)
    event = ChronicleEvent.objects.create(
        idempotency_key="local-private",
        source_app="staff",
        source_type="scene",
        source_id="1",
        kind="scene.curated",
        title="Local private event",
        summary="Old private event",
        visibility="participants",
        status="published",
    )
    event.participants.add(character)
    settings.MCP_OAUTH_ISSUER = "http://127.0.0.1/o"
    settings.MCP_RESOURCE_URL = "http://127.0.0.1/mcp"
    settings.MCP_ALLOWED_HOSTS = ("127.0.0.1",)
    application = Application.objects.create(
        user=account, name="Local fixture", client_type="public", authorization_grant_type="authorization-code"
    )
    for index, owner in enumerate((account, account2), 1):
        AccessToken.objects.create(
            user=owner,
            application=application,
            token=f"local-token-{index}",
            scope=" ".join(OAUTH_SCOPES),
            expires=timezone.now() + timedelta(minutes=5),
            resource=[settings.MCP_RESOURCE_URL],
        )
    app = create_application()
    writer_pids = []

    def write(phase):
        result = subprocess.run(
            [sys.executable, str(Path(__file__)), "writer", str(database), phase],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        record = json.loads(result.stdout.strip().splitlines()[-1])
        assert record["writer_pid"] != os.getpid()
        writer_pids.append(record["writer_pid"])

    async def exercise():
        async with app.app.router.lifespan_context(app.app):
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer local-token-1"}
                ) as http,
                streamable_http_client(settings.MCP_RESOURCE_URL, http_client=http) as (read, send, _),
                ClientSession(read, send) as session,
            ):
                await session.initialize()

                async def call(tool, identifier=character.pk):
                    result = await session.call_tool(tool, {"character_id": identifier})
                    assert not result.isError
                    return json.loads(result.content[0].text)

                initial = await call("get_my_character_summary")
                assert initial["name"] == cached_name and initial["vampire"]["hunger"] == 5
                assert (await session.call_tool("get_my_character_summary", {"character_id": foreign.pk})).isError
                write("update")
                current = await call("get_my_character_summary")
                assert current["name"] == "Persisted new name"
                assert current["stats"] == {"skills": {"stealth": 4}}
                assert current["vampire"] == {"hunger": 2}
                assert current["pools"] == {"health": 7}
                assert current["advantages"] == {"merits": ["Current merit"]}
                assert current["status"] == {"earned": 3, "position": "Persisted new position", "total": 4}
                assert current["boons"] == {"owed": 5, "held": 8, "net": 3}
                status_result = await call("get_my_status_and_boons")
                assert status_result["status"] == current["status"] and status_result["boons"] == current["boons"]
                write("transfer")
                for tool in ("get_my_character_summary", "get_my_status_and_boons"):
                    assert (await session.call_tool(tool, {"character_id": character.pk})).isError
                private = await session.call_tool("get_my_chronicle", {})
                assert not private.isError and "Local private event" not in str(private)
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer local-token-2"}
                ) as http,
                streamable_http_client(settings.MCP_RESOURCE_URL, http_client=http) as (read, send, _),
                ClientSession(read, send) as session,
            ):
                await session.initialize()
                summary = await session.call_tool("get_my_character_summary", {"character_id": character.pk})
                assert not summary.isError and json.loads(summary.content[0].text) == current
                private = await session.call_tool("get_my_chronicle", {})
                assert not private.isError and "Fresh private event" in str(private)

    async_to_sync(exercise)()
    assert character.key == cached_name and character.db.stats == cached_stats and character.account.pk == account.pk
    assert status.earned_status == 1 and position.name == "Old position" and ledger.total_debt_weight == 1
    print(
        json.dumps(
            {"gate": "mcp-process-freshness", "reader_pid": os.getpid(), "writer_pids": writer_pids, "passed": True}
        )
    )


def main():
    mode = sys.argv[1]
    if mode == "writer":
        bootstrap(sys.argv[2])
        write_fixture(sys.argv[2], sys.argv[3])
        return
    assert mode in {"narrative", "mcp"}
    with tempfile.TemporaryDirectory(prefix="beckoning-local-") as directory:
        database = Path(directory) / "acceptance.sqlite3"
        (Path(directory) / ".local-acceptance").touch()
        bootstrap(database)
        initialize()
        try:
            if mode == "narrative":
                narrative_http()
            else:
                mcp_freshness(database)
        finally:
            from django.db import connections

            connections.close_all()


if __name__ == "__main__":
    main()
