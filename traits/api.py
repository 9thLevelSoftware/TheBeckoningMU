"""
JSON API for web character creation and staff approval (mounted at /api/traits/).

The website form is the only way to make a player character. Every request
here is authorized with Evennia permission strings (web.permissions.has_perm),
never Django's is_staff:

- a character's owner is traits.CharacterBio.account;
- Builders review applications, but never their own (Admins may, and the
  reviewer is recorded either way); only Admins revoke an approval.

Rules live in world/rules_chargen.py and read world/v5_data.py. Anything that
changes the game world runs as one unit on the reactor (traits/utils.py,
handed over with web.main_thread.call_in_main_thread); views only parse,
validate and read before the hand-off.
"""

import json

from django.http import JsonResponse
from django.views import View
from evennia.utils import logger

from traits.models import CharacterBio
from traits.utils import (
    ChargenError,
    approve_unit,
    clean_ip,
    create_character_unit,
    name_problem,
    over_character_limit,
    reject_unit,
    resubmit_revoked_unit,
    resubmit_unit,
    revoke_unit,
    same_origin,
)
from web.main_thread import call_in_main_thread
from web.permissions import has_perm
from world import v5_data
from world.rules_chargen import (
    CONVICTION_RANGE,
    REQUIRED_TEXT,
    TEXT_LIMITS,
    SubmissionError,
    parse_submission,
    validate_v5_creation,
)

REVIEW_ACTIONS = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}


def error(message, status, **extra):
    errors = [message] if isinstance(message, str) else list(message)
    return JsonResponse({"error": "; ".join(errors), "errors": errors, **extra}, status=status)


class BaseAPIView(View):
    """Parses a JSON object body into request.json; anything else is a 400."""

    def dispatch(self, request, *args, **kwargs):
        request.json = {}
        if not request.user.is_authenticated:
            return error("Authentication required", 401)
        if request.method in ("POST", "PUT", "PATCH") and request.body:
            if request.content_type != "application/json":
                return error("Send the request body as application/json", 400)
            try:
                body = json.loads(request.body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return error("Invalid JSON", 400)
            if not isinstance(body, dict):
                return error("The request body must be a JSON object", 400)
            request.json = body
        return super().dispatch(request, *args, **kwargs)


def client_ip(request):
    """The request's address (REMOTE_ADDR, which Evennia rewrites from
    X-Forwarded-For for UPSTREAM_IPS) if it is a valid IP, else None."""
    return clean_ip(request.META.get("REMOTE_ADDR"))


def _staff_address_data(request, bio):
    """Addresses and same-origin hints, for Builders only (never the applicant)."""
    if not has_perm(request.user, "Builder"):
        return {}
    return {
        "applicant_ip": bio.applicant_ip,
        "reviewer_ip": bio.reviewer_ip,
        # A review made from the address the application came from: possibly
        # an alt account approving its own character (forbidden by policy).
        "reviewed_same_origin": same_origin(bio.applicant_ip, bio.reviewer_ip),
        "same_origin_as_you": same_origin(bio.applicant_ip, client_ip(request)),
    }


def _bio_or_404(character_id):
    return (
        CharacterBio.objects.select_related("character", "account", "reviewed_by")
        .filter(character_id=character_id)
        .first()
    )


def _is_owner(user, bio):
    return bio.account_id is not None and bio.account_id == user.id


def _can_view(user, bio):
    return _is_owner(user, bio) or has_perm(user, "Builder")


def _can_review(user, bio):
    """Builders review others' applications; only Admins and above may review their own."""
    return has_perm(user, "Builder") and (not _is_owner(user, bio) or has_perm(user, "Admin"))


def _parse_and_validate(data):
    """(Submission, errors). Errors are shape errors or V5 rule errors."""
    try:
        sub = parse_submission(data)
    except SubmissionError as err:
        return None, err.errors
    return sub, validate_v5_creation(sub)


# ----------------------------------------------------------------------------
# Rules data, served from world/v5_data.py
# ----------------------------------------------------------------------------


def _trait(name, category, category_name, **extra):
    data = {
        "name": name,
        "category": category,
        "category_name": category_name,
        "description": "",
        "min_value": 0,
        "max_value": 5,
        "is_instanced": False,
        "has_specialties": False,
        "splat_restriction": None,
    }
    data.update(extra)
    return data


def traits_for(category):
    """The trait list for one /api/traits/?category= value."""
    if category == "attributes":
        return [
            _trait(name, "attributes", "Attributes", group=group, min_value=1)
            for group, names in v5_data.ATTRIBUTES.items()
            for name in names
        ]
    if category == "skills":
        return [
            _trait(name, "skills", "Skills", group=group, has_specialties=True)
            for group, names in v5_data.SKILLS.items()
            for name in names
        ]
    if category == "disciplines":
        return [
            _trait(name, "disciplines", "Disciplines", description=data.get("description", ""))
            for name, data in v5_data.DISCIPLINES.items()
        ]
    if category == "advantages":
        backgrounds = [
            _trait(
                name,
                "advantages",
                "Advantages",
                kind="background",
                description=data.get("description", ""),
                min_value=1,
                max_value=data.get("max_dots", 5),
                dots=list(range(1, data.get("max_dots", 5) + 1)),
                is_instanced=bool(data.get("instanced")),
            )
            for name, data in v5_data.BACKGROUNDS.items()
        ]
        merits = [_advantage(name, data, "advantages", "Advantages", "merit") for name, data in v5_data.MERITS.items()]
        return backgrounds + merits
    if category == "flaws":
        return [_advantage(name, data, "flaws", "Flaws", "flaw") for name, data in v5_data.FLAWS.items()]
    return None


def _advantage(name, data, category, category_name, kind):
    return _trait(
        name,
        category,
        category_name,
        kind=kind,
        group=data.get("category"),
        description=data.get("description", ""),
        min_value=min(data["dots"]),
        max_value=max(data["dots"]),
        dots=list(data["dots"]),
        thin_blood=bool(data.get("thin_blood")),
        excluded_clans=list(data.get("excluded_clans", [])),
        splat_restriction="thin-blood" if data.get("thin_blood") else None,
    )


TRAIT_CATEGORIES = ("attributes", "skills", "disciplines", "advantages", "flaws")


class TraitCategoriesAPI(BaseAPIView):
    def get(self, request):
        return JsonResponse(
            {
                "categories": [
                    {"name": code.title(), "code": code, "description": "", "sort_order": index}
                    for index, code in enumerate(TRAIT_CATEGORIES, 1)
                ]
            }
        )


class TraitsAPI(BaseAPIView):
    """GET /api/traits/?category=attributes|skills|disciplines|advantages|flaws."""

    def get(self, request):
        category = request.GET.get("category")
        if category:
            traits = traits_for(category)
            if traits is None:
                return error(f"Unknown category: {category}", 400)
        else:
            traits = [trait for code in TRAIT_CATEGORIES for trait in traits_for(code)]
        return JsonResponse({"traits": traits})


class DisciplinePowersAPI(BaseAPIView):
    """GET /api/traits/discipline-powers/?discipline=&level=."""

    def get(self, request):
        discipline = (request.GET.get("discipline") or "").lower()
        level = request.GET.get("level")
        if level is not None and not level.isdigit():
            return error("Invalid level parameter", 400)
        powers = []
        for power in v5_data.DISCIPLINE_POWERS.values():
            if discipline and power["discipline"].lower() != discipline:
                continue
            if level is not None and power["level"] != int(level):
                continue
            amalgam_discipline, _, amalgam_level = (power.get("amalgam") or "").rpartition(" ")
            requirements = f"{power['discipline']} {power['level']}"
            if power.get("amalgam"):
                requirements += f", {power['amalgam']}"
            powers.append(
                {
                    "name": power["name"],
                    "discipline": power["discipline"],
                    "level": power["level"],
                    "description": power.get("description", ""),
                    "dice_pool": power.get("dice_pool") or "",
                    "rouse": power.get("rouse", 0),
                    "duration": power.get("duration_text") or power.get("duration") or "",
                    "amalgam_discipline": amalgam_discipline or None,
                    "amalgam_level": int(amalgam_level) if amalgam_level.isdigit() else None,
                    "requirements_text": requirements,
                }
            )
        return JsonResponse({"powers": powers})


def chargen_rules():
    """Everything the creation form needs to guide a player, from world/v5_data.py.

    The form reads its constants from here (GET /api/traits/rules/) so it
    can't drift from the server's validator, which reads the same tables.
    """

    def advantage_table(table):
        return {
            name: {
                "dots": list(data["dots"]),
                "group": data.get("category"),
                "description": data.get("description", ""),
                "thin_blood": bool(data.get("thin_blood")),
                "excluded_clans": list(data.get("excluded_clans", [])),
                "excludes": list(data.get("excludes", [])),
                "requires": list(data.get("requires", [])),
            }
            for name, data in table.items()
        }

    return {
        "attribute_spread": list(v5_data.CREATION_ATTRIBUTE_SPREAD),
        "skill_distributions": {
            name: {str(rating): count for rating, count in dist.items()}
            for name, dist in v5_data.CREATION_SKILL_DISTRIBUTIONS.items()
        },
        "free_specialty_skills": list(v5_data.CREATION_FREE_SPECIALTY_SKILLS),
        "extra_free_specialties": v5_data.CREATION_EXTRA_FREE_SPECIALTIES,
        "discipline_dots": list(v5_data.CREATION_DISCIPLINE_DOTS),
        "advantage_dots": v5_data.CREATION_ADVANTAGE_DOTS,
        "flaw_dots": v5_data.CREATION_FLAW_DOTS,
        "thin_blood_pairs": list(v5_data.CREATION_THIN_BLOOD_PAIRS),
        "humanity": v5_data.CREATION_HUMANITY,
        "attributes": v5_data.ATTRIBUTES,
        "skills": v5_data.SKILLS,
        "ages": {
            name: {
                "embraced": age["embraced"],
                "options": [
                    {
                        "generations": list(o["generations"]),
                        "blood_potency": o["blood_potency"],
                        "thin_blood": o["thin_blood"],
                    }
                    for o in age["options"]
                ],
                "xp": age["xp"],
                "extra_advantage_dots": age["extra_advantage_dots"],
                "extra_flaw_dots": age["extra_flaw_dots"],
                "humanity_change": age["humanity_change"],
            }
            for name, age in v5_data.GENERATION_BY_AGE.items()
        },
        "clans": {
            name: {
                "disciplines": list(clan["disciplines"]),
                "bane": clan.get("bane"),
                "compulsion": clan.get("compulsion"),
                "required_flaws": list(clan.get("required_flaws", [])),
                "excluded_merit_categories": list(clan.get("excluded_merit_categories", [])),
            }
            for name, clan in v5_data.CLANS.items()
        },
        "predator_types": {
            name: {
                "description": pred.get("description", ""),
                "specialties": [list(pair) for pair in pred.get("specialties", [])],
                "disciplines": list(pred.get("disciplines", [])),
                "discipline_clans": pred.get("discipline_clans", {}),
                "humanity": pred.get("humanity", 0),
                "blood_potency": pred.get("blood_potency", 0),
                "backgrounds": pred.get("backgrounds", []),
                "merits": pred.get("merits", []),
                "flaws": pred.get("flaws", []),
                "advantage_choices": pred.get("advantage_choices", []),
                "flaw_choices": pred.get("flaw_choices", []),
                "excluded_clans": pred.get("excluded_clans", []),
                "max_blood_potency": pred.get("max_blood_potency"),
                "note": pred.get("note", ""),
            }
            for name, pred in v5_data.PREDATOR_TYPES.items()
        },
        "disciplines": {
            name: {
                "description": data.get("description", ""),
                "powers": [
                    {
                        "name": power["name"],
                        "level": level,
                        "amalgam": power.get("amalgam"),
                        "description": power.get("description", ""),
                    }
                    for level, powers in sorted(data.get("powers", {}).items())
                    for power in powers
                ],
            }
            for name, data in v5_data.DISCIPLINES.items()
        },
        "backgrounds": {
            name: {
                "max_dots": data.get("max_dots", 5),
                "instanced": bool(data.get("instanced")),
                "description": data.get("description", ""),
            }
            for name, data in v5_data.BACKGROUNDS.items()
        },
        "merits": advantage_table(v5_data.MERITS),
        "flaws": advantage_table(v5_data.FLAWS),
        "rituals": [
            {"name": r["name"], "level": r["level"], "description": r.get("description", "")}
            for r in v5_data.DISCIPLINES["Blood Sorcery"].get("rituals", [])
        ],
        "formulas": [
            {"name": f["name"], "level": level, "description": f.get("description", "")}
            for level, formulas in sorted(v5_data.DISCIPLINES["Thin-Blood Alchemy"].get("formulas", {}).items())
            for f in formulas
        ],
        "conviction_range": list(CONVICTION_RANGE),
    }


class ChargenRulesAPI(BaseAPIView):
    """GET /api/traits/rules/: the creation rules the form applies."""

    def get(self, request):
        return JsonResponse(chargen_rules())


# ----------------------------------------------------------------------------
# Character sheet (read through the Character accessors)
# ----------------------------------------------------------------------------


def export_character(character):
    """The character sheet as JSON, read only through the Character accessors."""
    bio = character.bio
    return {
        "name": character.key,
        "clan": character.clan,
        "generation": character.generation,
        "predator_type": character.predator_type,
        "blood_potency": character.blood_potency,
        "humanity": character.humanity,
        "hunger": character.hunger,
        "health": character.health_max,
        "willpower": character.willpower_max,
        "attributes": {
            name: character.get_trait(name, "attributes") for names in v5_data.ATTRIBUTES.values() for name in names
        },
        "skills": {name: character.get_trait(name, "skills") for names in v5_data.SKILLS.values() for name in names},
        "specialties": character.specialties,
        "disciplines": character.discipline_levels,
        "discipline_powers": character.known_powers,
        "advantages": character.advantages,
        "xp": {"earned": character.xp_earned, "spent": character.xp_spent, "unspent": character.xp},
        "status": bio.status if bio else None,
    }


def _sheet_by_category(sheet):
    """The detail page's {category: [{name, rating, display_name}]} layout."""
    traits = {
        "Attributes": [{"name": n, "rating": r, "display_name": n} for n, r in sheet["attributes"].items()],
        "Skills": [],
        "Disciplines": [{"name": n, "rating": r, "display_name": n} for n, r in sheet["disciplines"].items()],
        "Advantages": [],
        "Flaws": [],
    }
    for name, rating in sheet["skills"].items():
        if rating:
            specialties = sheet["specialties"].get(v5_data.normalize_trait_name(name), [])
            label = f"{name} ({', '.join(specialties)})" if specialties else name
            traits["Skills"].append({"name": name, "rating": rating, "display_name": label})
    for name, value in sheet["advantages"]["backgrounds"].items():
        display = v5_data.resolve_trait(name, "backgrounds").name
        if isinstance(value, list):
            for instance in value:
                traits["Advantages"].append(
                    {"name": display, "rating": instance["dots"], "display_name": f"{display} ({instance['note']})"}
                )
        else:
            traits["Advantages"].append({"name": display, "rating": value, "display_name": display})
    for name, dots in sheet["advantages"]["merits"].items():
        traits["Advantages"].append({"name": name, "rating": dots, "display_name": name})
    for name, dots in sheet["advantages"]["flaws"].items():
        traits["Flaws"].append({"name": name, "rating": dots, "display_name": name})
    return traits


def _bio_data(bio, character):
    return {
        "full_name": bio.full_name,
        "concept": bio.concept,
        "ambition": bio.ambition,
        "desire": bio.desire,
        "sire": bio.sire,
        "background": bio.background,
        "clan": character.clan,
        "generation": character.generation,
        "predator_type": character.predator_type,
        "age": character.age_category,
        "status": bio.status,
        "approved": bio.status == "approved",
        "reviewed_by": bio.reviewed_by.username if bio.reviewed_by else None,
        "reviewed_at": bio.reviewed_at.isoformat() if bio.reviewed_at else None,
        "self_reviewed": bool(bio.reviewed_by_id and bio.reviewed_by_id == bio.account_id),
        "created_at": bio.created_at.isoformat() if bio.created_at else None,
        "rejection_notes": bio.rejection_notes,
        "rejection_count": bio.rejection_count,
    }


# ----------------------------------------------------------------------------
# Player endpoints
# ----------------------------------------------------------------------------


class CharacterValidationAPI(BaseAPIView):
    """POST a submission; answers {"valid", "errors"} without creating anything."""

    def post(self, request):
        sub, errors = _parse_and_validate(request.json)
        if sub and not errors:
            problem = name_problem(sub.name, request.user)
            errors = [problem] if problem else []
        return JsonResponse({"valid": not errors, "errors": errors})


class CharacterCreateAPI(BaseAPIView):
    """POST a submission (world.rules_chargen schema) to apply for a new character."""

    def post(self, request):
        sub, errors = _parse_and_validate(request.json)
        if errors:
            return error(errors, 400)
        problem = name_problem(sub.name, request.user)
        if problem:
            return error(problem, 400)
        limit = over_character_limit(request.user)
        if limit is not None:
            return error(f"You may have at most {limit} pending or approved characters", 400)
        try:
            character = call_in_main_thread(create_character_unit, request.user, sub, client_ip(request))
        except ChargenError as err:
            return error(err.errors, err.status)
        except Exception:
            logger.log_trace("Chargen: character creation failed")
            return error("Server error; no character was created", 500)
        return JsonResponse(
            {
                "success": True,
                "character_id": character.id,
                "character_name": character.key,
                "status": "submitted",
                "message": "Character submitted for approval",
            },
            status=201,
        )


class MyCharactersAPI(BaseAPIView):
    def get(self, request):
        data = []
        for bio in CharacterBio.objects.filter(account=request.user).select_related("character"):
            entry = {
                "character_id": bio.character_id,
                "character_name": bio.character.db_key,
                "status": bio.status,
                "clan": bio.character.clan,
                "concept": bio.concept,
                "rejection_count": bio.rejection_count,
                "created_at": bio.created_at.isoformat() if bio.created_at else None,
                "updated_at": bio.updated_at.isoformat() if bio.updated_at else None,
            }
            if bio.status in ("rejected", "revoked"):
                entry["rejection_notes"] = bio.rejection_notes
            data.append(entry)
        return JsonResponse({"characters": data})


class CharacterEditDataAPI(BaseAPIView):
    """The owner's last submission, to edit after a rejection or revocation."""

    def get(self, request, character_id):
        bio = _bio_or_404(character_id)
        if bio is None:
            return error("Character not found", 404)
        if not _is_owner(request.user, bio):
            return error("Permission denied", 403)
        if not bio.can_transition("submitted"):
            return error("Only rejected or revoked characters can be edited and resubmitted", 409)
        if bio.status == "revoked":
            # Revoking pauses play; the played sheet goes back for review as it is.
            return JsonResponse(
                {
                    "character_id": bio.character_id,
                    "mode": "revoked",
                    "narrative": _narrative(bio, bio.character),
                    "sheet": export_character(bio.character),
                    "rejection_notes": bio.rejection_notes,
                    "rejection_count": bio.rejection_count,
                }
            )
        return JsonResponse(
            {
                "character_id": bio.character_id,
                "mode": "rejected",
                "character_data": bio.submission,
                "rejection_notes": bio.rejection_notes,
                "rejection_count": bio.rejection_count,
            }
        )


class CharacterResubmitAPI(BaseAPIView):
    """POST a corrected submission for a rejected or revoked character."""

    def post(self, request, character_id):
        bio = _bio_or_404(character_id)
        if bio is None:
            return error("Character not found", 404)
        if not _is_owner(request.user, bio):
            return error("Permission denied", 403)
        if not bio.can_transition("submitted"):
            return error("Only rejected or revoked characters can be resubmitted", 409)
        if bio.status == "revoked":
            narrative, errors = _parse_narrative(request.json, bio)
            if errors:
                return error(errors, 400)
            unit, args = resubmit_revoked_unit, (bio.pk, request.user, narrative)
        else:
            sub, errors = _parse_and_validate(request.json)
            if errors:
                return error(errors, 400)
            if sub.name.lower() != bio.character.db_key.lower():
                problem = name_problem(sub.name, request.user, exclude_id=bio.character_id)
                if problem:
                    return error(problem, 400)
            unit, args = resubmit_unit, (bio.pk, request.user, sub)
        try:
            call_in_main_thread(unit, *args)
        except ChargenError as err:
            return error(err.errors, err.status)
        except CharacterBio.TransitionError as err:
            return error(str(err), 409)
        except Exception:
            logger.log_trace("Chargen: resubmission failed")
            return error("Server error; the character was not changed", 500)
        return JsonResponse(
            {"success": True, "character_id": bio.character_id, "message": "Character resubmitted for approval"}
        )


NARRATIVE_KEYS = ("concept", "sire", "ambition", "desire", "background")


def _narrative(bio, character):
    return {"name": character.db_key, **{key: getattr(bio, key) for key in NARRATIVE_KEYS}}


def _parse_narrative(data, bio):
    """A revoked character's resubmission: only narrative text may change."""
    unknown = sorted(str(key) for key in data if key not in NARRATIVE_KEYS)
    if unknown:
        return None, [f"A revoked character keeps its sheet; only {', '.join(NARRATIVE_KEYS)} can change "
                      f"(unknown key(s): {', '.join(unknown)})"]  # fmt: skip
    narrative, errors = {}, []
    for key in NARRATIVE_KEYS:
        value = data.get(key, getattr(bio, key))
        if not isinstance(value, str):
            errors.append(f"{key}: must be text")
            continue
        value = value.strip()
        if key in REQUIRED_TEXT and not value:
            errors.append(f"{key}: is required")
        if len(value) > TEXT_LIMITS[key]:
            errors.append(f"{key}: at most {TEXT_LIMITS[key]} characters")
        narrative[key] = value
    return narrative, errors


class CharacterExportAPI(BaseAPIView):
    def get(self, request, character_id):
        bio = _bio_or_404(character_id)
        if bio is None:
            return error("Character not found", 404)
        if not _can_view(request.user, bio):
            return error("Permission denied", 403)
        sheet = export_character(bio.character)
        return JsonResponse({"character_data": sheet, "character_name": bio.character.db_key})


# ----------------------------------------------------------------------------
# Staff endpoints
# ----------------------------------------------------------------------------


class PendingCharactersAPI(BaseAPIView):
    """Applications for staff: ?status=submitted,rejected (default) or approved, revoked."""

    def get(self, request):
        if not has_perm(request.user, "Builder"):
            return error("Builder permission required", 403)
        wanted = [s for s in (request.GET.get("status") or "submitted,rejected").split(",") if s]
        bios = (
            CharacterBio.objects.filter(status__in=wanted)
            .select_related("character", "account", "reviewed_by")
            .order_by("created_at")
        )
        data = []
        for bio in bios:
            data.append(
                {
                    "character_id": bio.character_id,
                    "character_name": bio.character.db_key,
                    "player_name": bio.account.username if bio.account else None,
                    "clan": bio.character.clan,
                    "concept": bio.concept,
                    "status": bio.status,
                    "rejection_count": bio.rejection_count,
                    "submitted_date": bio.created_at.isoformat() if bio.created_at else None,
                    "reviewed_by": bio.reviewed_by.username if bio.reviewed_by else None,
                    "can_review": _can_review(request.user, bio),
                    "same_origin_as_you": same_origin(bio.applicant_ip, client_ip(request)),
                }
            )
        return JsonResponse({"pending_characters": data})


class CharacterDetailAPI(BaseAPIView):
    def get(self, request, character_id):
        bio = _bio_or_404(character_id)
        if bio is None:
            return error("Character not found", 404)
        if not _can_view(request.user, bio):
            return error("Permission denied", 403)
        character = bio.character
        sheet = export_character(character)
        powers = []
        for name in sheet["discipline_powers"]:
            power = v5_data.find_power(name) or {}
            powers.append(
                {
                    "name": name,
                    "discipline": power.get("discipline"),
                    "level": power.get("level"),
                    "description": power.get("description", ""),
                    "requirements": f"{power.get('discipline')} {power.get('level')}"
                    + (f", {power['amalgam']}" if power.get("amalgam") else ""),
                }
            )
        return JsonResponse(
            {
                "character_id": character.id,
                "character_name": character.db_key,
                "player_name": bio.account.username if bio.account else None,
                "bio": {**_bio_data(bio, character), **_staff_address_data(request, bio)},
                "sheet": sheet,
                "traits": _sheet_by_category(sheet),
                "powers": powers,
                "can_review": _can_review(request.user, bio),
                "can_revoke": has_perm(request.user, "Admin"),
                "same_origin_as_you": _staff_address_data(request, bio).get("same_origin_as_you", False),
            }
        )


class CharacterApprovalAPI(BaseAPIView):
    """POST {"action": "approve"|"reject"|"revoke", "notes": "..."}."""

    def post(self, request, character_id):
        if not has_perm(request.user, "Builder"):
            return error("Builder permission required", 403)
        bio = _bio_or_404(character_id)
        if bio is None:
            return error("Character not found", 404)
        action = request.json.get("action")
        notes = request.json.get("notes") or ""
        if action not in REVIEW_ACTIONS:
            return error('Invalid action. Use "approve", "reject" or "revoke"', 400)
        if not isinstance(notes, str) or len(notes) > 5000:
            return error("Notes must be text of at most 5000 characters", 400)
        if action == "revoke" and not has_perm(request.user, "Admin"):
            return error("Only Admins can revoke an approval", 403)
        if not _can_review(request.user, bio):
            return error("You can't review your own character; another staff member must", 403)
        if action == "reject" and not notes.strip():
            return error("Say what needs to change when you reject a character", 400)
        if not bio.can_transition(REVIEW_ACTIONS[action]):
            return error(f"An application that is {bio.status} can't be {REVIEW_ACTIONS[action]}", 409)

        unit = {"approve": approve_unit, "reject": reject_unit, "revoke": revoke_unit}[action]
        try:
            bio = call_in_main_thread(unit, bio.pk, request.user, notes.strip(), client_ip(request))
        except ChargenError as err:
            return error(err.errors, err.status)
        except CharacterBio.TransitionError as err:
            return error(str(err), 409)
        except Exception:
            logger.log_trace(f"Chargen: {action} failed")
            return error(f"Server error; the character was not {REVIEW_ACTIONS[action]}", 500)
        return JsonResponse(
            {
                "success": True,
                "action": action,
                "status": bio.status,
                "character_name": bio.character.db_key,
                "reviewed_by": request.user.username,
                "reviewed_at": bio.reviewed_at.isoformat() if bio.reviewed_at else None,
                "self_reviewed": bio.account_id == request.user.id,
                "same_origin": same_origin(bio.applicant_ip, bio.reviewer_ip),
            }
        )
