"""Marshal authenticated web writes onto Evennia's game thread."""

import threading
from functools import wraps
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from twisted.internet import reactor
from twisted.python.threadable import isInIOThread


def run_sync_in_main_thread(function):
    """Dispatch using the calling thread, not Evennia's import-time thread flag."""
    if isInIOThread():
        return function()
    if not reactor.running:
        raise TimeoutError("Game reactor is not running")
    done = threading.Event()
    lock = threading.Lock()
    state = {"cancelled": False}

    def execute():
        with lock:
            if state["cancelled"]:
                return
        try:
            state["result"] = function()
        except Exception as error:
            state["error"] = error
        finally:
            done.set()

    reactor.callFromThread(execute)
    if not done.wait(timeout=30):
        with lock:
            state["cancelled"] = True
        raise TimeoutError("Game write timed out")
    if "error" in state:
        raise state["error"]
    return state["result"]


def game_thread_write(method):
    @wraps(method)
    def dispatch(view, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        account_id = request.user.pk
        payload = request.json

        def execute():
            accounts = get_user_model().objects.filter(pk=account_id, is_active=True)
            authority = accounts.values("is_staff", "is_superuser", "username").first()
            if authority is None:
                return JsonResponse({"error": "Authentication required"}, status=401)
            account = accounts.get()
            # Evennia's idmapper can retain the pre-revocation Python instance.
            for field, value in authority.items():
                setattr(account, field, value)
            tracked = {}

            def track_object(obj):
                tracked.setdefault(
                    (type(obj), obj.pk),
                    (obj, [(attr.pk, attr) for attr in obj.attributes.all()], getattr(obj, "db_location_id", None)),
                )

            def restore():
                from evennia.objects.models import ObjectDB

                from .utils import refresh_character_attribute_cache

                rooms = set()
                for (model, pk), (obj, attributes, old_location) in tracked.items():
                    rooms.update((old_location, getattr(obj, "db_location_id", None)))
                    fields = [field.attname for field in model._meta.concrete_fields]
                    row = model.objects.filter(pk=pk).values(*fields).first()
                    refresh_character_attribute_cache(obj, attributes)
                    if row is None:
                        obj.flush_from_cache(force=True)
                        obj.pk = None
                    else:
                        for field, value in row.items():
                            setattr(obj, field, value)
                        obj._state.fields_cache.clear()
                        obj.locks.reset()
                for room in ObjectDB.objects.filter(pk__in=rooms - {None}):
                    room.contents_cache.init()

            try:
                with transaction.atomic():
                    track_object(account)
                    response = method(
                        view, SimpleNamespace(user=account, json=payload, track_object=track_object), *args, **kwargs
                    )
                    failed = response.status_code >= 400
                    if failed:
                        transaction.set_rollback(True)
            except Exception:
                restore()
                raise
            if failed:
                restore()
            return response

        try:
            return run_sync_in_main_thread(execute)
        except TimeoutError:
            return JsonResponse(
                {"error": "Game server unavailable; check your character list before retrying."}, status=503
            )

    return dispatch
