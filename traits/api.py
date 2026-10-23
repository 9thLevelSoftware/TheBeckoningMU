"""
Web API endpoints for enhanced character creation and trait management.
Provides JSON-based endpoints for web-based character applications.
"""

import json

from django.db import models, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from .models import CharacterBio, CharacterPower, CharacterTrait, DisciplinePower, Trait, TraitCategory
from .utils import (
    enhanced_import_character_from_json,
    export_character_to_json,
    get_available_traits_for_character,
)
from .web_bridge import game_thread_write


def load_character(character_id, *, refresh=False):
    """Resolve current persisted ownership even when Evennia holds an old instance."""
    query = ObjectDB.objects.filter(pk=character_id, db_typeclass_path__contains="characters")
    character = query.get()
    if refresh:
        fields = [field.attname for field in ObjectDB._meta.concrete_fields]
        row = query.values(*fields).get()
        for field, value in row.items():
            setattr(character, field, value)
        character._state.fields_cache.clear()
    return character


def owns_character(account, character):
    return ObjectDB.objects.filter(pk=character.pk, db_account_id=account.pk).exists()


def notify_account(account, message, notification_type="info"):
    """Store a notification for delivery on next login, and try immediate delivery."""
    from django.utils import timezone as tz

    if not account.db.pending_notifications:
        account.db.pending_notifications = []
    account.db.pending_notifications.append(
        {
            "message": message,
            "type": notification_type,
            "timestamp": tz.now().isoformat(),
            "read": False,
        }
    )
    # Try immediate delivery if player is online
    if account.sessions.count():
        account.msg(message)


def place_approved_character(character):
    """Move an approved character to the starting room. Sets home and location."""
    from django.conf import settings as django_settings
    from evennia.objects.models import ObjectDB

    start_location = getattr(django_settings, "START_LOCATION", "#2")
    try:
        room_id = int(start_location.strip("#")) if isinstance(start_location, str) else int(start_location)
        start_room = ObjectDB.objects.get(id=room_id)
    except (ValueError, ObjectDB.DoesNotExist):
        # Fallback to Limbo (#2)
        start_room = ObjectDB.objects.get(id=2)

    if not character.move_to(start_room, quiet=True):
        raise ValueError("Could not place approved character in the starting room")
    character.home = start_room
    character.save(update_fields=["db_home"])
    if character.db_account:
        character.db_account.characters.add(character)
        character.locks.add(
            f"puppet:id({character.id}) or pid({character.db_account_id}) or perm(Developer) or pperm(Developer)"
        )


class BaseAPIView(View):
    """Base class for API views with common functionality."""

    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to handle JSON parsing."""
        if request.user.is_authenticated:
            authority = (
                AccountDB.objects.filter(pk=request.user.pk, is_active=True)
                .values("is_staff", "is_superuser", "username")
                .first()
            )
            if authority is None:
                return JsonResponse({"error": "Authentication required"}, status=401)
            for field, value in authority.items():
                setattr(request.user, field, value)
        if request.content_type == "application/json" and hasattr(request, "body"):
            try:
                request.json = json.loads(request.body.decode("utf-8"))
                if not isinstance(request.json, dict):
                    return JsonResponse({"error": "JSON body must be an object"}, status=400)
            except (ValueError, UnicodeDecodeError):
                return JsonResponse({"error": "Invalid JSON"}, status=400)
        else:
            request.json = {}

        return super().dispatch(request, *args, **kwargs)


class TraitCategoriesAPI(BaseAPIView):
    """API endpoint for trait categories."""

    def get(self, request):
        """Get all trait categories."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        categories = TraitCategory.objects.all()
        data = []

        for category in categories:
            data.append(
                {
                    "id": category.id,
                    "name": category.name,
                    "code": category.code,
                    "description": category.description,
                    "sort_order": category.sort_order,
                }
            )

        return JsonResponse({"categories": data})


class TraitsAPI(BaseAPIView):
    """API endpoint for traits."""

    def get(self, request):
        """Get traits, optionally filtered by category or splat."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        category_code = request.GET.get("category")
        splat = request.GET.get("splat", "mortal")

        traits = Trait.objects.filter(is_active=True)

        if category_code:
            traits = traits.filter(category__code=category_code)

        # Filter by splat restriction
        if splat:
            traits = traits.filter(
                models.Q(splat_restriction__isnull=True)
                | models.Q(splat_restriction="")
                | models.Q(splat_restriction=splat)
            )

        traits = traits.select_related("category").order_by("category__sort_order", "sort_order", "name")

        data = []
        for trait in traits:
            data.append(
                {
                    "id": trait.id,
                    "name": trait.name,
                    "category": trait.category.code,
                    "category_name": trait.category.name,
                    "description": trait.description,
                    "min_value": trait.min_value,
                    "max_value": trait.max_value,
                    "is_instanced": trait.is_instanced,
                    "has_specialties": trait.has_specialties,
                    "splat_restriction": trait.splat_restriction,
                }
            )

        return JsonResponse({"traits": data})


class DisciplinePowersAPI(BaseAPIView):
    """API endpoint for discipline powers."""

    def get(self, request):
        """Get discipline powers, optionally filtered by discipline."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        discipline_name = request.GET.get("discipline")
        level = request.GET.get("level")

        powers = DisciplinePower.objects.filter(is_active=True)

        if discipline_name:
            powers = powers.filter(discipline__name__iexact=discipline_name)

        if level:
            try:
                powers = powers.filter(level=int(level))
            except ValueError:
                return JsonResponse({"error": "Invalid level parameter"}, status=400)

        powers = powers.select_related("discipline", "amalgam_discipline").order_by(
            "discipline__name", "level", "sort_order", "name"
        )

        data = []
        for power in powers:
            data.append(
                {
                    "id": power.id,
                    "name": power.name,
                    "discipline": power.discipline.name,
                    "level": power.level,
                    "description": power.description,
                    "dice_pool": power.dice_pool,
                    "cost": power.cost,
                    "duration": power.duration,
                    "amalgam_discipline": power.amalgam_discipline.name if power.amalgam_discipline else None,
                    "amalgam_level": power.amalgam_level,
                    "requirements_text": power.requirements_text,
                }
            )

        return JsonResponse({"powers": data})


class CharacterValidationAPI(BaseAPIView):
    """API endpoint for character validation."""

    def post(self, request):
        """Validate character data without creating the character."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        character_data = request.json

        if not character_data:
            return JsonResponse({"error": "No character data provided"}, status=400)

        # Create a temporary character object for validation
        temp_char = ObjectDB()
        temp_char.db_key = character_data.get("name", "TempChar")

        # Run validation
        results = enhanced_import_character_from_json(temp_char, character_data, validate_only=True)

        return JsonResponse(
            {
                "valid": results["success"],
                "errors": results["validation_errors"] + results["errors"],
                "warnings": results["warnings"],
                "summary": {
                    "traits_validated": results["imported_traits"],
                    "specialties_validated": results["imported_specialties"],
                    "powers_validated": results["imported_powers"],
                },
            }
        )


class CharacterImportAPI(BaseAPIView):
    """API endpoint for character import."""

    @game_thread_write
    def post(self, request):
        """Import character data to an existing character."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff permissions required"}, status=403)

        character_name = request.json.get("character_name")
        character_data = request.json.get("character_data")
        account_name = request.json.get("account_name")

        if not all([character_name, character_data, account_name]):
            return JsonResponse(
                {"error": "Missing required fields: character_name, character_data, account_name"}, status=400
            )

        try:
            # Get the account
            account = AccountDB.objects.get(username__iexact=account_name)

            # Get the character
            character = ObjectDB.objects.get(
                db_key__iexact=character_name, db_account=account, db_typeclass_path__contains="characters"
            )

        except AccountDB.DoesNotExist:
            return JsonResponse({"error": "Account not found"}, status=404)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        character = load_character(character.pk, refresh=True)
        request.track_object(character)
        # Import the character data
        results = enhanced_import_character_from_json(character, character_data)

        return JsonResponse(
            {
                "success": results["success"],
                "errors": results["errors"],
                "warnings": results["warnings"],
                "imported": {
                    "traits": results["imported_traits"],
                    "specialties": results["imported_specialties"],
                    "powers": results["imported_powers"],
                },
                "validation_errors": results["validation_errors"],
            }
        )


class CharacterExportAPI(BaseAPIView):
    """API endpoint for character export."""

    def get(self, request, character_id):
        """Export character data to JSON format."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        try:
            character = load_character(character_id)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        # Enforce ownership: only the character's owner or staff can export
        if not owns_character(request.user, character) and not request.user.is_staff:
            return JsonResponse({"error": "Permission denied"}, status=403)

        include_powers = request.GET.get("include_powers", "true").lower() == "true"

        character_data = export_character_to_json(character, include_powers=include_powers)

        return JsonResponse(
            {
                "character_data": character_data,
                "character_name": character.key,
                "exported_at": character_data.get("updated_at", "unknown"),
            }
        )


class CharacterAvailableTraitsAPI(BaseAPIView):
    """API endpoint for getting available traits for a character."""

    def get(self, request, character_id):
        """Get all traits available to a specific character based on their splat."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        try:
            character = load_character(character_id)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        # Enforce ownership: only the character's owner or staff can view available traits
        if not owns_character(request.user, character) and not request.user.is_staff:
            return JsonResponse({"error": "Permission denied"}, status=403)

        available_traits = get_available_traits_for_character(character)

        data = []
        for trait in available_traits:
            data.append(
                {
                    "id": trait.id,
                    "name": trait.name,
                    "category": trait.category.code,
                    "category_name": trait.category.name,
                    "description": trait.description,
                    "min_value": trait.min_value,
                    "max_value": trait.max_value,
                    "is_instanced": trait.is_instanced,
                    "has_specialties": trait.has_specialties,
                    "splat_restriction": trait.splat_restriction,
                }
            )

        return JsonResponse({"available_traits": data})


class PendingCharactersAPI(BaseAPIView):
    """API endpoint for listing characters awaiting approval."""

    def get(self, request):
        """Get list of characters pending approval."""
        # Check staff permissions
        if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
            return JsonResponse({"error": "Staff permissions required"}, status=403)

        # Get all characters with CharacterBio that are submitted or rejected (not draft, not approved)
        pending_bios = (
            CharacterBio.objects.filter(status__in=["submitted", "rejected"])
            .select_related("character")
            .order_by("created_at")
        )

        data = []
        for bio in pending_bios:
            character = bio.character
            player_name = character.db_account.username if character.db_account else "None"

            data.append(
                {
                    "character_id": character.id,
                    "character_name": character.db_key,
                    "player_name": player_name,
                    "clan": bio.clan,
                    "submitted_date": bio.created_at.isoformat() if bio.created_at else None,
                    "concept": bio.concept,
                    "status": bio.status,
                    "rejection_count": bio.rejection_count,
                }
            )

        return JsonResponse({"pending_characters": data})


class CharacterDetailAPI(BaseAPIView):
    """API endpoint for getting full character sheet data for review."""

    def get(self, request, character_id):
        """Get complete character data for staff review."""
        # Check staff permissions
        if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
            return JsonResponse({"error": "Staff permissions required"}, status=403)

        try:
            character = load_character(character_id)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        # Get character bio
        try:
            bio = CharacterBio.objects.get(character=character)
            bio_data = {
                "full_name": bio.full_name,
                "concept": bio.concept,
                "ambition": bio.ambition,
                "desire": bio.desire,
                "clan": bio.clan,
                "sire": bio.sire,
                "generation": bio.generation,
                "predator_type": bio.predator_type,
                "splat": bio.splat,
                "status": bio.status,
                "approved": bio.approved,
                "approved_by": bio.approved_by,
                "approved_at": bio.approved_at.isoformat() if bio.approved_at else None,
                "created_at": bio.created_at.isoformat() if bio.created_at else None,
                "background": bio.background,
                "rejection_notes": bio.rejection_notes,
                "rejection_count": bio.rejection_count,
            }
        except CharacterBio.DoesNotExist:
            bio_data = {}

        # Get character traits grouped by category
        traits = (
            CharacterTrait.objects.filter(character=character)
            .select_related("trait", "trait__category")
            .order_by("trait__category__sort_order", "trait__sort_order")
        )

        traits_by_category = {}
        for char_trait in traits:
            category_name = char_trait.trait.category.name
            if category_name not in traits_by_category:
                traits_by_category[category_name] = []

            trait_data = {
                "name": char_trait.trait.name,
                "rating": char_trait.rating,
                "specialty": char_trait.specialty,
                "instance_name": char_trait.instance_name,
                "display_name": char_trait.display_name,
            }
            traits_by_category[category_name].append(trait_data)

        # Get character powers
        powers = CharacterPower.objects.filter(character=character).select_related("power", "power__discipline")
        powers_data = []
        for char_power in powers:
            powers_data.append(
                {
                    "name": char_power.power.name,
                    "discipline": char_power.power.discipline.name,
                    "level": char_power.power.level,
                    "description": char_power.power.description,
                    "requirements": char_power.power.requirements_text,
                }
            )

        return JsonResponse(
            {
                "character_id": character.id,
                "character_name": character.db_key,
                "player_name": character.db_account.username if character.db_account else "None",
                "bio": bio_data,
                "traits": traits_by_category,
                "powers": powers_data,
            }
        )


class CharacterCreateAPI(BaseAPIView):
    """API endpoint for creating new characters from web form."""

    @game_thread_write
    def post(self, request):
        """Create a new character with submitted data."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        character_data = request.json.get("character_data")
        if not isinstance(character_data, dict) or not character_data:
            return JsonResponse({"error": "Missing or invalid character_data"}, status=400)

        character_name = character_data.get("name")
        if not isinstance(character_name, str) or not character_name.strip():
            return JsonResponse({"error": "Character name is required"}, status=400)
        character_name = character_name.strip()
        character_data = {**character_data, "name": character_name}
        validation = enhanced_import_character_from_json(ObjectDB(), character_data, validate_only=True)
        if not validation["success"]:
            return JsonResponse(
                {"error": "; ".join(validation["errors"] + validation["validation_errors"])}, status=400
            )
        if ObjectDB.objects.filter(db_key__iexact=character_name, db_account=request.user).exists():
            return JsonResponse({"error": "You already have a character with that name"}, status=400)

        from evennia.utils import create

        character = create.create_object(
            typeclass="typeclasses.characters.Character",
            key=character_name,
            location=None,
            home=None,
            nohome=True,
        )
        request.track_object(character)
        character.db_account = request.user
        character.save(update_fields=["db_account"])
        # Submitted applications become playable only after staff approval.
        character.locks.add("puppet:perm(Developer) or pperm(Developer)")
        results = enhanced_import_character_from_json(character, character_data)
        if not results["success"]:
            transaction.set_rollback(True)
            return JsonResponse({"error": "; ".join(results["errors"] + results["validation_errors"])}, status=400)
        bio = CharacterBio.objects.get(character=character)
        bio.status = "submitted"
        bio.background = character_data.get("background", "")
        bio.save()
        return JsonResponse(
            {
                "success": True,
                "character_id": character.id,
                "character_name": character.db_key,
                "message": "Character created and submitted for approval",
            }
        )


class CharacterApprovalAPI(BaseAPIView):
    """API endpoint for approving or rejecting characters."""

    @game_thread_write
    def post(self, request, character_id):
        """Approve or reject a character."""
        # Check staff permissions
        if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
            return JsonResponse({"error": "Staff permissions required"}, status=403)

        try:
            character = load_character(character_id, refresh=True)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        request.track_object(character)
        if character.db_account:
            request.track_object(character.db_account)
        try:
            bio = CharacterBio.objects.select_for_update().get(character=character)
        except CharacterBio.DoesNotExist:
            return JsonResponse({"error": "Character bio not found"}, status=404)

        action = request.json.get("action")
        notes = request.json.get("notes", "")
        if not isinstance(notes, str):
            return JsonResponse({"error": "Notes must be text"}, status=400)

        if action not in ["approve", "reject"]:
            return JsonResponse({"error": 'Invalid action. Must be "approve" or "reject"'}, status=400)

        # Idempotent approval check: prevent double-approval race condition
        if action == "approve" and bio.status == "approved":
            return JsonResponse({"error": "Character already approved", "approved_by": bio.approved_by}, status=409)

        if bio.status != "submitted":
            return JsonResponse({"error": "Only submitted applications can be reviewed"}, status=409)

        if action == "approve":
            place_approved_character(character)

        # Update character bio
        if action == "approve":
            bio.status = "approved"
        else:
            bio.status = "rejected"
            bio.rejection_notes = notes
            bio.rejection_count += 1

        bio.approved_by = request.user.username
        bio.approved_at = timezone.now()
        bio.save()

        stats = character.db.stats
        stats["approved"] = action == "approve"
        stats["approved_by"] = request.user.username if action == "approve" else ""
        if character.db.chargen:
            character.db.chargen["approved"] = action == "approve"

        # Store approval notes in character attributes
        if notes:
            character.db.approval_notes = notes

        # Auto-place approved character and send notifications
        if action == "approve":
            if character.db_account:
                msg = f"Your character '{character.db_key}' has been APPROVED!\nYou may now begin playing."
                if notes:
                    msg += f"\nStaff notes: {notes}"
                transaction.on_commit(
                    lambda: notify_account(character.db_account, msg, notification_type="approval"), robust=True
                )
        else:
            # Rejection notification
            if character.db_account:
                msg = f"Your character '{character.db_key}' requires revisions.\n"
                msg += f"Staff feedback:\n{notes}\n"
                msg += "Please edit and resubmit via the character creation page."
                transaction.on_commit(
                    lambda: notify_account(character.db_account, msg, notification_type="rejection"), robust=True
                )

        return JsonResponse(
            {
                "success": True,
                "action": action,
                "character_name": character.db_key,
                "approved_by": request.user.username,
                "approved_at": bio.approved_at.isoformat(),
            }
        )


class MyCharactersAPI(BaseAPIView):
    """API endpoint returning all characters owned by the authenticated user."""

    def get(self, request):
        """Get list of characters owned by the current user with their status."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        characters = ObjectDB.objects.filter(db_account=request.user, db_typeclass_path__contains="characters")

        data = []
        for character in characters:
            try:
                bio = CharacterBio.objects.get(character=character)
            except CharacterBio.DoesNotExist:
                continue

            char_data = {
                "character_id": character.id,
                "character_name": character.db_key,
                "status": bio.status,
                "clan": bio.clan,
                "concept": bio.concept,
                "rejection_count": bio.rejection_count,
                "created_at": bio.created_at.isoformat() if bio.created_at else None,
                "updated_at": bio.updated_at.isoformat() if bio.updated_at else None,
            }

            if bio.status == "rejected":
                char_data["rejection_notes"] = bio.rejection_notes

            data.append(char_data)

        return JsonResponse({"characters": data})


class CharacterEditDataAPI(BaseAPIView):
    """API endpoint returning full character data for editing a rejected character."""

    def get(self, request, character_id):
        """Get complete character data for editing after rejection."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        try:
            character = load_character(character_id)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        # Verify ownership
        if not owns_character(request.user, character):
            return JsonResponse({"error": "Permission denied"}, status=403)

        try:
            bio = CharacterBio.objects.get(character=character)
        except CharacterBio.DoesNotExist:
            return JsonResponse({"error": "Character bio not found"}, status=404)

        if bio.status != "rejected":
            return JsonResponse({"error": "Only rejected characters can be edited for resubmission"}, status=400)

        # Use existing export to get trait data
        character_data = export_character_to_json(character, include_powers=True)

        # Merge in bio fields not included in export
        character_data["background"] = bio.background
        character_data["ambition"] = bio.ambition
        character_data["desire"] = bio.desire
        character_data["sire"] = bio.sire
        character_data["generation"] = bio.generation
        character_data["predator_type"] = bio.predator_type
        character_data["full_name"] = bio.full_name
        character_data["concept"] = bio.concept
        character_data["clan"] = bio.clan
        character_data["splat"] = bio.splat

        return JsonResponse(
            {
                "character_id": character.id,
                "character_data": character_data,
                "rejection_notes": bio.rejection_notes,
                "rejection_count": bio.rejection_count,
            }
        )


class CharacterResubmitAPI(BaseAPIView):
    """API endpoint for resubmitting a rejected character."""

    @game_thread_write
    def post(self, request, character_id):
        """Resubmit a rejected character with updated data."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        try:
            character = load_character(character_id, refresh=True)
        except ObjectDB.DoesNotExist:
            return JsonResponse({"error": "Character not found"}, status=404)

        # Verify ownership
        if not owns_character(request.user, character):
            return JsonResponse({"error": "Permission denied"}, status=403)

        request.track_object(character)
        if character.db_account:
            request.track_object(character.db_account)
        try:
            bio = CharacterBio.objects.select_for_update().get(character=character)
        except CharacterBio.DoesNotExist:
            return JsonResponse({"error": "Character bio not found"}, status=404)

        if bio.status != "rejected":
            return JsonResponse({"error": "Only rejected characters can be resubmitted"}, status=400)

        character_data = request.json.get("character_data")
        if not isinstance(character_data, dict) or not character_data:
            return JsonResponse({"error": "Missing or invalid character_data"}, status=400)

        new_name = character_data.get("name")
        if not isinstance(new_name, str) or not new_name.strip():
            return JsonResponse({"error": "Character name is required"}, status=400)
        new_name = new_name.strip()
        character_data = {**character_data, "name": new_name}
        if ObjectDB.objects.filter(db_key__iexact=new_name, db_account=request.user).exclude(pk=character.pk).exists():
            return JsonResponse({"error": "You already have a character with that name"}, status=400)

        # Re-import traits from updated data
        results = enhanced_import_character_from_json(character, character_data)

        if not results["success"]:
            transaction.set_rollback(True)
            errors = results["errors"] + results["validation_errors"]
            error_msg = "; ".join(errors) if errors else "Unknown error during import"
            return JsonResponse({"error": f"Failed to import character data: {error_msg}"}, status=400)

        bio.refresh_from_db()
        # Update bio fields from character_data
        bio.full_name = character_data.get("name", bio.full_name)
        bio.concept = character_data.get("concept", bio.concept)
        bio.clan = character_data.get("clan", bio.clan)
        bio.sire = character_data.get("sire", bio.sire)
        bio.generation = character_data.get("generation", bio.generation)
        bio.predator_type = character_data.get("predator_type", bio.predator_type)
        bio.ambition = character_data.get("ambition", bio.ambition)
        bio.desire = character_data.get("desire", bio.desire)
        bio.background = character_data.get("background", bio.background)

        character.db_key = new_name
        character.save(update_fields=["db_key"])

        # Reset status for re-review
        bio.status = "submitted"
        bio.rejection_notes = ""
        bio.approved_by = ""
        bio.approved_at = None
        bio.save()

        return JsonResponse(
            {"success": True, "character_id": character.id, "message": "Character resubmitted for approval"}
        )


# URL patterns for inclusion in main urls.py
def get_api_urls():
    """Return URL patterns for the trait API."""
    from django.urls import path

    return [
        path("api/traits/categories/", TraitCategoriesAPI.as_view(), name="trait_categories_api"),
        path("api/traits/", TraitsAPI.as_view(), name="traits_api"),
        path("api/discipline-powers/", DisciplinePowersAPI.as_view(), name="discipline_powers_api"),
        path("api/character/validate/", CharacterValidationAPI.as_view(), name="character_validation_api"),
        path("api/character/import/", CharacterImportAPI.as_view(), name="character_import_api"),
        path("api/character/<int:character_id>/export/", CharacterExportAPI.as_view(), name="character_export_api"),
        path(
            "api/character/<int:character_id>/available-traits/",
            CharacterAvailableTraitsAPI.as_view(),
            name="character_available_traits_api",
        ),
    ]
