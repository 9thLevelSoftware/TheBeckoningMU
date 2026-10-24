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

    from traits.models import CharacterBio

    accounts = [
        evennia.create_account(f"LocalAccount{index}", email=None, password="local-fixture-only") for index in (1, 2)
    ]
    characters = []
    for index, account in enumerate(accounts, 1):
        character = evennia.create_object("typeclasses.characters.Character", key=f"LocalCharacter{index}", nohome=True)
        character.account = account
        character.set_trait("Strength", 4)
        character.set_trait("Brawl", 3)
        character.set_trait("Wits", 4)
        character.set_trait("Streetwise", 3)
        character.set_trait("Stealth", 3)
        character.hunger = 5
        character.blood_potency = 1
        character.clan = "Brujah"
        character.predator_type = "Alleycat"
        CharacterBio.objects.create(character=character, account=account, status="approved")
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
            self.disconnected = []
            self.late_responses = []

        def render_POST(self, request):  # noqa: N802
            payload = json.loads(request.content.read())
            assert request.path == b"/chat/completions"
            assert request.getHeader("Authorization") == "Bearer local-fixture-only"
            self.received.append(payload)
            pending = StoryGenerationRequest.objects.latest("id")
            assert pending.status == "pending" and pending.action_text
            mode = self.mode

            def disconnected(_failure):
                self.disconnected.append(pending.pk)
                return None

            request.notifyFinish().addErrback(disconnected)
            # The result is visible before the first byte of provider traffic.
            shown = "\n".join(str(call.args[0]) for call in character.msg.call_args_list)
            assert shown.count("SUCCESSFUL HUNT") == 1
            assert "Hunger 5 -> 3" in shown and "Hunger dice:" in shown

            def heartbeat():
                if StoryGenerationRequest.objects.get(pk=pending.pk).status == "pending":
                    self.heartbeats.append(pending.pk)

            def respond():
                if mode == "late-valid":
                    self.late_responses.append(pending.pk)
                    assert StoryGenerationRequest.objects.get(pk=pending.pk).status == "failed"
                    if pending.pk in self.disconnected:
                        return
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
            if mode == "headers-stall":
                return NOT_DONE_YET
            if mode == "body-stall":
                request.write(b'{"choices":[')
                return NOT_DONE_YET
            if mode == "declared-overflow":
                request.setHeader(b"Content-Length", b"2048")
                request.write(b"{")
                return NOT_DONE_YET
            if mode == "chunked-overflow":
                request.write(b" " * 200)
                reactor.callLater(0.03, request.write, b" " * 200)
                return NOT_DONE_YET
            if mode == "socket-abort":
                request.write(b'{"choices":[')
                reactor.callLater(0.03, request.transport.abortConnection)
                return NOT_DONE_YET
            reactor.callLater(0.5 if mode == "late-valid" else 0.15, respond)
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
            command("/story start downtown")
            assert "opt-in" in str(character.msg.call_args)
            command("/story opt-in")
            assert NarrativeConsent.objects.get(character=character).opted_in
            for action in ("start downtown", "resume I wait.", "complete"):
                command("/story " + action)
            assert StorySession.objects.count() == StoryGenerationRequest.objects.count() == 0
            assert get_hunger(character) == 5
            settings.NARRATIVE_AI = {
                "endpoint": f"http://127.0.0.1:{listener.getHost().port}/chat/completions",
                "model": "local-fixture",
                "api_key": "local-fixture-only",
                "request_timeout_seconds": 0.3,
                "connect_timeout_seconds": 0.2,
                "response_max_bytes": 256,
            }
            with (
                patch("dice.dice_roller.randint", return_value=8) as dice,
                patch("commands.v5.utils.hunting_utils.random.randint", return_value=100),
                patch("commands.v5.utils.hunting_utils.random.choices", return_value=["Sanguine"]),
                patch("commands.v5.utils.hunting_utils.random.choice", side_effect=lambda values: values[0]),
            ):
                command("/story start downtown")
                session = StorySession.objects.get(character=character, status="active")
                outcome = dict(session.deterministic_outcome)
                assert outcome["schema_version"] == 1
                assert outcome["dice"] == {"regular": [8, 8], "hunger": [8] * 5}
                assert outcome["pool"]["rolled"] == 7
                assert outcome["hunger_before"] == 5 and outcome["hunger_after"] == 3
                assert get_hunger(character) == 3 and dice.call_count == 7, (get_hunger(character), dice.call_count)
                first = yield wait_for_request()
                assert first.status == "succeeded" and first.action_text == ""
                assert first.response == "A local shadow moves. |r"
                assert "||r" in str(character.msg.call_args)
                modes = (
                    "valid",
                    "http-error",
                    "malformed",
                    "citation",
                    "mutation",
                    "headers-stall",
                    "body-stall",
                    "chunked-overflow",
                    "declared-overflow",
                    "socket-abort",
                    "late-valid",
                )
                for mode in modes:
                    endpoint.mode = mode
                    command("/story resume I watch from the doorway.")
                    request = yield wait_for_request()
                    assert request.status == ("succeeded" if mode == "valid" else "failed"), mode
                    assert request.action_text == ""
                    assert (bool(request.response)) == (mode == "valid")
                    if mode in ("headers-stall", "body-stall", "late-valid"):
                        assert request.error == "timeout", (mode, request.error)
                    if mode in ("chunked-overflow", "declared-overflow"):
                        assert request.error == "response_too_large", (mode, request.error)
                    if mode == "late-valid":
                        yield task.deferLater(reactor, 0.25, lambda: None)
                        request.refresh_from_db()
                        assert request.status == "failed" and request.response == ""
                        assert request.pk in endpoint.late_responses
                    if mode in ("headers-stall", "body-stall", "chunked-overflow", "declared-overflow", "late-valid"):
                        yield task.deferLater(reactor, 0.03, lambda: None)
                        assert request.pk in endpoint.disconnected, mode
                    session.refresh_from_db()
                    assert session.current_action == ""
                    assert session.deterministic_outcome == outcome
                    assert get_hunger(character) == 3 and dice.call_count == 7
                    shown = "\n".join(str(call.args[0]) for call in character.msg.call_args_list)
                    assert shown.count("SUCCESSFUL HUNT") == 1
                    if mode != "valid":
                        assert "story request failed" in str(character.msg.call_args)
                assert "A local shadow moves." in endpoint.received[1]["messages"][-1]["content"]
                endpoint.mode = "valid"
                command("/story start downtown")  # existing session must not resolve a second hunt
                yield wait_for_request()
                assert dice.call_count == 7 and StorySession.objects.count() == 1
                command("/story complete")
                session.refresh_from_db()
                assert session.status == "completed" and session.current_action == ""
                assert not session.requests.exclude(action_text="").exists()
                # Closing a scene does not bypass the ordinary hunt cooldown.
                command("/story start downtown")
                assert "already hunted" in str(character.msg.call_args)
                assert StorySession.objects.count() == 1 and dice.call_count == 7
                command("/story opt-out")
                assert not NarrativeConsent.objects.get(character=character).opted_in
                # Ordinary deterministic hunting continues to work without any provider.
                settings.NARRATIVE_AI = {}
                command("/story status")
                assert "Hunger 5 -> 3" in str(character.msg.call_args)
                assert dice.call_count == 7
                command(" downtown")
                assert "already hunted" in str(character.msg.call_args)
                assert dice.call_count == 7 and get_hunger(character) == 3
                character.last_hunt -= 25 * 3600  # a later night's ordinary hunt
                command(" downtown")
                assert dice.call_count == 14 and get_hunger(character) == 1
                command(" downtown")
                assert "without a kill" in str(character.msg.call_args)
                assert dice.call_count == 14 and get_hunger(character) == 1
                assert StoryGenerationRequest.objects.count() == len(modes) + 2
            assert len(endpoint.received) == len(modes) + 2
            assert len(endpoint.heartbeats) >= 7
            print(
                json.dumps(
                    {
                        "gate": "command-http",
                        "requests": len(endpoint.received),
                        "heartbeats_while_pending": len(endpoint.heartbeats),
                        "aborted_connections": len(endpoint.disconnected),
                        "passed": True,
                    }
                )
            )
        finally:
            yield listener.stopListening()

    task.react(exercise)


def write_fixture(database, phase):
    import evennia
    from evennia.objects.models import ObjectDB

    evennia._init()
    from boons.models import Boon
    from chronicle.models import ChronicleEvent
    from status.models import CamarillaPosition, CharacterStatus

    character = ObjectDB.objects.get(db_key="LocalCharacter1" if phase == "update" else "Persisted new name")
    if phase == "update":
        character.set_trait("Stealth", 4)
        character.set_trait("Stamina", 4)
        character.hunger = 2
        character.set_damage("health", superficial=1, aggravated=2)
        character.set_advantage("merits", "Beautiful", 0)
        character.set_advantage("merits", "Stunning", 4)
        ObjectDB.objects.filter(pk=character.pk).update(db_key="Persisted new name")
        CharacterStatus.objects.filter(character=character).update(earned_status=3, position_status=1)
        CamarillaPosition.objects.update(name="Persisted new position")
        Boon.objects.filter(debtor=character).update(boon_type="life")
        Boon.objects.filter(creditor=character).update(status="accepted")
        other = ObjectDB.objects.get(db_key="LocalCharacter2")
        Boon.objects.create(debtor=other, creditor=character, boon_type="life", status="accepted")
    elif phase == "transfer":
        from evennia.accounts.models import AccountDB

        from traits.models import CharacterBio

        owner = AccountDB.objects.get(username="LocalAccount2")
        CharacterBio.objects.filter(character=character).update(account=owner)
        ChronicleEvent.objects.filter(idempotency_key="local-private").update(summary="Fresh private event")
    elif phase == "withdraw":
        from evennia.accounts.models import AccountDB

        from chronicle.services import redact_event

        source = ChronicleEvent.objects.get(idempotency_key="local-source")
        actor = AccountDB.objects.get(username="LocalModerator")
        redact_event(source.pk, actor, expected_version=source.version)
    else:
        raise AssertionError("Unknown fixture writer phase")
    print(json.dumps({"writer_pid": os.getpid(), "phase": phase}))


def mcp_freshness(database):
    import asyncio
    import socket
    from datetime import timedelta
    from urllib.parse import urlsplit

    import httpx
    import uvicorn
    from asgiref.sync import async_to_sync
    from django.conf import settings
    from django.utils import timezone
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from oauth2_provider.models import AccessToken, Application

    from boons.models import Boon
    from chronicle.availability import source_context
    from chronicle.models import ChronicleEvent, ChronicleGenerationRequest
    from chronicle.services import begin_correction, event_projection, publish_event, staff_events
    from mcp_server.app import create_application
    from mcp_server.auth import OAUTH_SCOPES
    from status.models import CamarillaPosition, CharacterStatus
    from traits.models import CharacterBio

    (account, account2), (character, foreign) = fixtures()
    character.set_damage("health", superficial=1)
    character.set_advantage("merits", "Beautiful", 2)
    cached_stats = character.db.stats
    cached_name = character.key
    cached_bio = CharacterBio.objects.get(character=character)
    position = CamarillaPosition.objects.create(name="Old position")
    status = CharacterStatus.objects.create(character=character, earned_status=1, position=position)
    debt = Boon.objects.create(debtor=character, creditor=foreign, boon_type="trivial", status="accepted")
    credit = Boon.objects.create(debtor=foreign, creditor=character, boon_type="major", status="offered")
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
    import evennia

    moderator = evennia.create_account("LocalModerator", email=None, password="local-fixture-only")
    moderator.permissions.add("Builder")
    source = ChronicleEvent.objects.create(
        idempotency_key="local-source",
        source_app="staff",
        source_type="scene",
        source_id="2",
        kind="scene.curated",
        title="Source awaiting later redaction",
        summary="A public source for the retained local recap.",
        visibility="public",
        status="published",
    )
    _selected, fingerprints = source_context([source.pk])
    request = ChronicleGenerationRequest.objects.create(
        requested_by=moderator,
        mode="recap",
        source_ids=[str(source.pk)],
        source_fingerprints=fingerprints,
        status="succeeded",
    )
    recap = ChronicleEvent.objects.create(
        idempotency_key="local-recap",
        source_app="chronicle",
        source_type="ChronicleGenerationRequest",
        source_id=str(request.pk),
        kind="scene.curated",
        title="Retained generated recap",
        summary="Successful generated prose retained for staff source review.",
        visibility="public",
        status="published",
        ai_generated=True,
    )
    recap.source_events.add(source)
    request.draft_event = recap
    request.save(update_fields=["draft_event"])
    correction = begin_correction(recap.pk, moderator, changes={"title": "Corrected retained recap"})
    correction = publish_event(correction.pk, moderator, expected_version=correction.version)
    descendant = ChronicleEvent.objects.create(
        idempotency_key="local-descendant",
        source_app="staff",
        source_type="scene",
        source_id="3",
        kind="scene.curated",
        title="Transitive corrected-source recap",
        summary="A retained descendant depending on the corrected recap.",
        visibility="public",
        status="published",
    )
    descendant.source_events.add(correction)
    warmed_correction = ChronicleEvent.objects.prefetch_related("source_events", "participants").get(pk=correction.pk)
    warmed_descendant = ChronicleEvent.objects.prefetch_related("source_events", "participants").get(pk=descendant.pk)
    retained_prose = {recap.pk: recap.summary, correction.pk: correction.summary, descendant.pk: descendant.summary}
    protected_ids = {source.pk, recap.pk, correction.pk, descendant.pk}
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    settings.MCP_OAUTH_ISSUER = origin + "/o"
    settings.MCP_RESOURCE_URL = origin + "/mcp"
    settings.MCP_ALLOWED_HOSTS = (f"127.0.0.1:{port}",)
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
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on", timeout_graceful_shutdown=3)
    )
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
        serving = asyncio.create_task(server.serve(sockets=[listener]))

        async def local_only(request):
            parsed = urlsplit(str(request.url))
            assert parsed.scheme == "http" and parsed.netloc == f"127.0.0.1:{port}", "Non-fixture HTTP refused"

        http_options = {"timeout": 8, "trust_env": False, "event_hooks": {"request": [local_only]}}
        try:
            async with asyncio.timeout(8):
                while not server.started:
                    if serving.done():
                        await serving
                    await asyncio.sleep(0.01)
            async with (
                httpx.AsyncClient(**http_options, headers={"Authorization": "Bearer local-token-1"}) as http,
                streamable_http_client(settings.MCP_RESOURCE_URL, http_client=http) as (read, send, _),
                ClientSession(read, send) as session,
            ):
                await session.initialize()

                async def call(tool, identifier=character.pk):
                    result = await session.call_tool(tool, {"character_id": identifier})
                    assert not result.isError
                    return json.loads(result.content[0].text)

                initial = await call("get_my_character_summary")
                for tool in ("get_public_chronicle", "get_my_chronicle"):
                    warm = await session.call_tool(tool, {})
                    assert not warm.isError
                    rows = [json.loads(block.text) for block in warm.content]
                    assert {source.pk, correction.pk, descendant.pk}.issubset({row["id"] for row in rows})
                    assert recap.pk not in {row["id"] for row in rows}
                assert initial["name"] == cached_name and initial["vampire"]["hunger"] == 5
                assert initial["boons"] == {"owed": 1, "held": 0, "net": -1}
                assert (await session.call_tool("get_my_character_summary", {"character_id": foreign.pk})).isError
                write("update")
                current = await call("get_my_character_summary")
                assert current["name"] == "Persisted new name"
                assert current["stats"]["skills"]["physical"]["stealth"] == 4
                assert current["stats"]["attributes"]["physical"]["stamina"] == 4
                assert current["stats"]["attributes"]["physical"]["strength"] == 4
                assert current["vampire"]["hunger"] == 2 and current["vampire"]["clan"] == "Brujah"
                assert current["pools"] == {
                    "health": {"superficial": 1, "aggravated": 2},
                    "willpower": {"superficial": 0, "aggravated": 0},
                }
                assert current["advantages"]["merits"] == {"Stunning": 4}
                assert current["status"] == {"earned": 3, "position": "Persisted new position", "total": 4}
                assert current["boons"] == {"owed": 5, "held": 8, "net": 3}
                status_result = await call("get_my_status_and_boons")
                assert status_result["status"] == current["status"] and status_result["boons"] == current["boons"]
                write("transfer")
                for tool in ("get_my_character_summary", "get_my_status_and_boons"):
                    assert (await session.call_tool(tool, {"character_id": character.pk})).isError
                private = await session.call_tool("get_my_chronicle", {})
                assert not private.isError and "Local private event" not in str(private)
                write("withdraw")
                for tool in ("get_public_chronicle", "get_my_chronicle"):
                    refreshed = await session.call_tool(tool, {})
                    assert not refreshed.isError
                    rows = [json.loads(block.text) for block in refreshed.content]
                    assert protected_ids.isdisjoint(row["id"] for row in rows)
                    assert all(prose not in str(refreshed) for prose in retained_prose.values())
                assert event_projection(warmed_correction) is None
                assert event_projection(warmed_descendant, "account", account) is None
            async with (
                httpx.AsyncClient(**http_options, headers={"Authorization": "Bearer local-token-2"}) as http,
                streamable_http_client(settings.MCP_RESOURCE_URL, http_client=http) as (read, send, _),
                ClientSession(read, send) as session,
            ):
                await session.initialize()
                summary = await session.call_tool("get_my_character_summary", {"character_id": character.pk})
                assert not summary.isError and json.loads(summary.content[0].text) == current
                private = await session.call_tool("get_my_chronicle", {})
                assert not private.isError and "Fresh private event" in str(private)
                assert protected_ids.isdisjoint(json.loads(block.text)["id"] for block in private.content)
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(serving, timeout=8)
            finally:
                listener.close()
                from asgiref.sync import sync_to_async
                from django.db import connections

                await sync_to_async(connections.close_all, thread_sensitive=True)()
                connections.close_all()

    async_to_sync(exercise)()
    assert character.key == cached_name and character.db.stats == cached_stats and character.account.pk == account.pk
    assert character.hunger == 5 and character.damage["health"] == {"superficial": 1, "aggravated": 0}
    assert character.advantages["merits"] == {"Beautiful": 2}
    assert cached_bio.account_id == account.pk
    assert status.earned_status == 1 and position.name == "Old position"
    assert debt.boon_type == "trivial" and credit.status == "offered"
    request.refresh_from_db()
    assert request.status == "succeeded" and request.source_fingerprints == fingerprints
    assert ChronicleEvent.objects.get(pk=source.pk).summary == ""
    for event_id, prose in retained_prose.items():
        retained = staff_events(moderator).get(pk=event_id)
        assert retained.summary == prose
        assert retained.status == ("superseded" if event_id == recap.pk else "withdrawn")
        if event_id != recap.pk:
            assert retained.withdrawal_reason == "source_redacted" and retained.withdrawn_by_id == moderator.pk
    print(
        json.dumps(
            {
                "gate": "mcp-process-freshness",
                "reader_pid": os.getpid(),
                "writer_pids": writer_pids,
                "transport": "owned-loopback-http",
                "withdrawal": {"transitive_corrected_source": True, "retained_successful_prose": True},
                "passed": True,
            }
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
