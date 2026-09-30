"""
Staff character approval commands for VtM 5e character generation.

These commands allow staff to review, edit, approve, and reject character
applications using the traits system.
"""

from evennia.commands.command import Command
from evennia.commands.cmdset import CmdSet
from traits.models import CharacterTrait, CharacterPower, CharacterBio, Trait, TraitCategory
from traits.utils import (
    get_character_trait_value,
    set_character_trait_value,
    validate_trait_for_character,
    enhanced_import_character_from_json
)
from traits.api import place_approved_character, notify_account
from evennia.utils.search import object_search
from evennia.utils import evtable
from django.utils import timezone
import datetime

# Import Jobs system for approval integration
try:
    from jobs.models import Job, Bucket, Comment
    JOBS_AVAILABLE = True
except ImportError:
    JOBS_AVAILABLE = False
import json
import os
from django.conf import settings

# Import trait constants from v5_data - single source of truth
from world.v5_data import CLANS, ATTRIBUTES, SKILLS

# Derive lists from v5_data constants for backward compatibility
VALID_CLANS = list(CLANS.keys())

# Attributes - derive from ATTRIBUTES dict (lowercase for consistency)
PHYSICAL_ATTRIBUTES = [attr.lower() for attr in ATTRIBUTES['Physical']]
SOCIAL_ATTRIBUTES = [attr.lower() for attr in ATTRIBUTES['Social']]
MENTAL_ATTRIBUTES = [attr.lower() for attr in ATTRIBUTES['Mental']]

# Skills - derive from SKILLS dict (lowercase for consistency)
PHYSICAL_SKILLS = [skill.lower() for skill in SKILLS['Physical']]
SOCIAL_SKILLS = [skill.lower() for skill in SKILLS['Social']]
MENTAL_SKILLS = [skill.lower() for skill in SKILLS['Mental']]


class CmdPending(Command):
    """
    List all characters awaiting staff approval.

    Usage:
        +pending

    Shows all characters that have been submitted for approval but not yet
    approved or rejected. Characters are listed with their player, clan,
    and submission time.
    """

    key = "+pending"
    aliases = ["pending"]
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Staff"

    def func(self):
        """List pending characters."""
        # Get all characters with CharacterBio that are submitted or rejected
        pending_bios = CharacterBio.objects.filter(
            status__in=['submitted', 'rejected']
        ).select_related('character')

        if not pending_bios:
            self.caller.msg("|yNo characters currently pending approval.|n")
            return

        # Sort by creation time (oldest first)
        pending_bios = pending_bios.order_by('created_at')

        self.caller.msg("|w" + "=" * 78 + "|n")
        self.caller.msg("|wCharacters Pending Approval|n")
        self.caller.msg("|w" + "=" * 78 + "|n")

        for idx, bio in enumerate(pending_bios, 1):
            character = bio.character
            player = character.account.key if character.account else "None"
            clan = bio.clan or "Not set"
            
            # Calculate time since submission
            time_pending = timezone.now() - bio.created_at
            days_pending = time_pending.days
            hours_pending = time_pending.seconds // 3600
            
            if days_pending > 0:
                time_str = f"{days_pending}d {hours_pending}h ago"
            else:
                time_str = f"{hours_pending}h ago"

            self.caller.msg(
                f"|w{idx}.|n {character.key:<20} |c(Player: {player})|n\n"
                f"    Clan: |y{clan:<15}|n  Submitted: |g{time_str}|n"
            )

        self.caller.msg("|w" + "=" * 78 + "|n")
        self.caller.msg(f"|wTotal pending: {len(pending_bios)}|n")


class CmdReview(Command):
    """
    Display a full character sheet for review.

    Usage:
        +review <character name>

    Shows the complete character sheet including attributes, skills, disciplines,
    specialties, and character background information. This provides all the
    information needed to approve or reject a character.
    """

    key = "+review"
    aliases = ["review"]
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Staff"

    def func(self):
        """Display character sheet."""
        if not self.args:
            self.caller.msg("Usage: +review <character name>")
            return

        # Find the character
        results = object_search(self.args.strip(), typeclass="typeclasses.characters.Character")
        
        if not results:
            self.caller.msg(f"|rCharacter '{self.args}' not found.|n")
            return
        
        if len(results) > 1:
            self.caller.msg("|rMultiple characters found. Please be more specific.|n")
            return

        character = results[0]

        # Get character bio
        try:
            bio = character.vtm_bio
        except AttributeError:
            self.caller.msg("|rThis character has no bio information.|n")
            return

        # Build the character sheet display
        output = []
        output.append("|w" + "=" * 78 + "|n")
        output.append(f"|wCharacter Review: {character.key}|n")
        output.append("|w" + "=" * 78 + "|n")
        
        # Basic info
        output.append(f"|wName:|n {bio.full_name or character.key}")
        output.append(f"|wConcept:|n {bio.concept or 'Not set'}")
        output.append(f"|wClan:|n {bio.clan or 'Not set'}")
        output.append(f"|wSire:|n {bio.sire or 'Not set'}")
        output.append(f"|wGeneration:|n {bio.generation or 'Not set'}")
        output.append(f"|wPredator Type:|n {bio.predator_type or 'Not set'}")
        output.append(f"|wPlayer:|n {character.account.key if character.account else 'None'}")
        output.append("")

        # Get all character traits
        char_traits = CharacterTrait.objects.filter(character=character).select_related('trait__category')

        # Physical Attributes
        output.append("|w--- Physical Attributes ---|n")
        for attr in PHYSICAL_ATTRIBUTES:
            rating = get_character_trait_value(character, attr)
            dots = "|g" + "●" * rating + "|x" + "○" * (5 - rating) if rating > 0 else "○" * 5
            output.append(f"  {attr.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Social Attributes
        output.append("|w--- Social Attributes ---|n")
        for attr in SOCIAL_ATTRIBUTES:
            rating = get_character_trait_value(character, attr)
            dots = "|g" + "●" * rating + "|x" + "○" * (5 - rating) if rating > 0 else "○" * 5
            output.append(f"  {attr.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Mental Attributes
        output.append("|w--- Mental Attributes ---|n")
        for attr in MENTAL_ATTRIBUTES:
            rating = get_character_trait_value(character, attr)
            dots = "|g" + "●" * rating + "|x" + "○" * (5 - rating) if rating > 0 else "○" * 5
            output.append(f"  {attr.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Physical Skills
        output.append("|w--- Physical Skills ---|n")
        for skill in PHYSICAL_SKILLS:
            rating = get_character_trait_value(character, skill)
            if rating > 0:
                dots = "|c" + "●" * rating + "|x" + "○" * (5 - rating)
                output.append(f"  {skill.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Social Skills
        output.append("|w--- Social Skills ---|n")
        for skill in SOCIAL_SKILLS:
            rating = get_character_trait_value(character, skill)
            if rating > 0:
                dots = "|c" + "●" * rating + "|x" + "○" * (5 - rating)
                output.append(f"  {skill.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Mental Skills
        output.append("|w--- Mental Skills ---|n")
        for skill in MENTAL_SKILLS:
            rating = get_character_trait_value(character, skill)
            if rating > 0:
                dots = "|c" + "●" * rating + "|x" + "○" * (5 - rating)
                output.append(f"  {skill.capitalize():<15} {dots} ({rating})")
        output.append("")

        # Disciplines
        disciplines = char_traits.filter(trait__category__code='disciplines')
        if disciplines:
            output.append("|w--- Disciplines ---|n")
            for disc in disciplines.order_by('trait__name'):
                rating = disc.rating
                dots = "|r" + "●" * rating + "|x" + "○" * (5 - rating) if rating > 0 else "○" * 5
                output.append(f"  {disc.trait.name:<15} {dots} ({rating})")
            output.append("")

        # Specialties
        specialties = char_traits.filter(specialty__isnull=False)
        if specialties:
            output.append("|w--- Specialties ---|n")
            for spec in specialties.order_by('trait__name'):
                output.append(f"  {spec.trait.name}: |y{spec.specialty}|n")
            output.append("")

        # Approval status
        output.append("|w--- Approval Status ---|n")
        if bio.approved:
            output.append(f"  |gAPPROVED|n by {bio.approved_by} on {bio.approved_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            output.append(f"  |yPENDING APPROVAL|n")
            output.append(f"  Submitted: {bio.created_at.strftime('%Y-%m-%d %H:%M')}")

        output.append("|w" + "=" * 78 + "|n")

        self.caller.msg("\n".join(output))


class CmdCharEdit(Command):
    """
    Edit a character's traits and information.

    Usage:
        +charedit <character>/<field>=<value>

    Edit character traits and bio information. All edits are logged with
    the staff member's name, timestamp, and reason.

    Supported fields:
        Bio: name, concept, clan, generation, sire, predator_type
        Attributes: strength, dexterity, stamina, charisma, manipulation,
                   composure, intelligence, wits, resolve
        Skills: All standard VtM 5e skills
        Disciplines: celerity, fortitude, potence, etc.

    Examples:
        +charedit John/clan=Brujah
        +charedit Mary/strength=3
        +charedit Bob/academics=2
        +charedit Sarah/celerity=2

    After entering the command, you'll be prompted for an edit reason.
    """

    key = "+charedit"
    aliases = ["charedit"]
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Staff"

    def func(self):
        """Edit character traits."""
        if not self.args or '/' not in self.args or '=' not in self.args:
            self.caller.msg("Usage: +charedit <character>/<field>=<value>")
            return

        # Parse command
        try:
            char_name, rest = self.args.split('/', 1)
            field, value = rest.split('=', 1)
            char_name = char_name.strip()
            field = field.strip().lower()
            value = value.strip()
        except ValueError:
            self.caller.msg("Usage: +charedit <character>/<field>=<value>")
            return

        # Find character
        results = object_search(char_name, typeclass="typeclasses.characters.Character")
        
        if not results:
            self.caller.msg(f"|rCharacter '{char_name}' not found.|n")
            return
        
        if len(results) > 1:
            self.caller.msg("|rMultiple characters found. Please be more specific.|n")
            return

        character = results[0]

        # Get or create bio
        bio, created = CharacterBio.objects.get_or_create(character=character)

        # Handle bio fields
        bio_fields = ['name', 'concept', 'clan', 'generation', 'sire', 'predator_type']
        
        if field in bio_fields:
            if field == 'name':
                bio.full_name = value
                bio.save()
                self.caller.msg(f"|gSet {character.key}'s full name to '{value}'.|n")
            elif field == 'concept':
                bio.concept = value
                bio.save()
                self.caller.msg(f"|gSet {character.key}'s concept to '{value}'.|n")
            elif field == 'clan':
                if value not in VALID_CLANS:
                    self.caller.msg(f"|rInvalid clan. Valid clans: {', '.join(VALID_CLANS)}|n")
                    return
                bio.clan = value
                bio.save()
                self.caller.msg(f"|gSet {character.key}'s clan to '{value}'.|n")
            elif field == 'generation':
                try:
                    gen_value = int(value)
                    if gen_value < 1 or gen_value > 16:
                        self.caller.msg("|rGeneration must be between 1 and 16.|n")
                        return
                    bio.generation = gen_value
                    bio.save()
                    self.caller.msg(f"|gSet {character.key}'s generation to {gen_value}.|n")
                except ValueError:
                    self.caller.msg("|rGeneration must be a number.|n")
                    return
            elif field == 'sire':
                bio.sire = value
                bio.save()
                self.caller.msg(f"|gSet {character.key}'s sire to '{value}'.|n")
            elif field == 'predator_type':
                bio.predator_type = value
                bio.save()
                self.caller.msg(f"|gSet {character.key}'s predator type to '{value}'.|n")

            # Log the edit
            self._log_edit(character, field, value, "Bio field edit")
            return

        # Handle trait fields (attributes, skills, disciplines, etc.)
        try:
            rating = int(value)
        except ValueError:
            self.caller.msg("|rTrait rating must be a number.|n")
            return

        # Validate trait value
        is_valid, error_msg = validate_trait_for_character(character, field, rating)
        if not is_valid:
            self.caller.msg(f"|r{error_msg}|n")
            return

        # Set the trait
        success = set_character_trait_value(character, field, rating)
        
        if success:
            self.caller.msg(f"|gSet {character.key}'s {field} to {rating}.|n")
            self._log_edit(character, field, value, "Trait edit")
        else:
            self.caller.msg(f"|rFailed to set {field} to {rating}.|n")

    def _log_edit(self, character, field, value, reason):
        """Log the edit in character's db attributes."""
        if not hasattr(character.db, 'staff_edits'):
            character.db.staff_edits = []
        
        edit_log = {
            'staff': self.caller.key,
            'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'field': field,
            'value': value,
            'reason': reason
        }
        character.db.staff_edits.append(edit_log)


class CmdApprove(Command):
    """
    Approve a character for play.

    Usage:
        +approve <character>[=<message>]

    Approves a character, marking them as ready for play. An optional
    message can be included which will be sent to the player along with
    the approval notification.

    Examples:
        +approve John
        +approve Mary=Great character! Welcome to the game.
    """

    key = "+approve"
    aliases = ["approve"]
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Staff"

    def func(self):
        """Approve a character."""
        if not self.args:
            self.caller.msg("Usage: +approve <character>[=<message>]")
            return

        # Parse arguments
        char_name = self.args
        message = None
        
        if '=' in self.args:
            char_name, message = self.args.split('=', 1)
            char_name = char_name.strip()
            message = message.strip()

        # Find character
        results = object_search(char_name, typeclass="typeclasses.characters.Character")
        
        if not results:
            self.caller.msg(f"|rCharacter '{char_name}' not found.|n")
            return
        
        if len(results) > 1:
            self.caller.msg("|rMultiple characters found. Please be more specific.|n")
            return

        character = results[0]

        # Get or create bio
        bio, created = CharacterBio.objects.get_or_create(character=character)

        if bio.status == 'approved':
            self.caller.msg(f"|yCharacter '{character.key}' is already approved.|n")
            return

        # Approve the character
        bio.status = 'approved'
        bio.approved_by = self.caller.key
        bio.approved_at = timezone.now()
        bio.save()

        # Auto-place approved character in starting room
        place_approved_character(character)

        # Notify staff
        self.caller.msg(f"|gCharacter '{character.key}' has been approved!|n")
        self.caller.msg(f"|gCharacter placed in starting room.|n")

        # Notify player (stores for offline delivery and sends immediately if online)
        if character.account:
            msg = f"Your character '{character.key}' has been APPROVED by {self.caller.key}!\nYou may now begin playing."
            if message:
                msg += f"\nStaff message: {message}"
            notify_account(character.account, msg, notification_type="approval")

        # Log the approval
        if not hasattr(character.db, 'staff_actions'):
            character.db.staff_actions = []

        character.db.staff_actions.append({
            'action': 'approved',
            'staff': self.caller.key,
            'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': message or ''
        })

        # Close related Job in Jobs system if it exists
        if JOBS_AVAILABLE:
            try:
                # Find Job for this character (created during +chargen/finalize)
                jobs = Job.objects.filter(
                    title__icontains=f"Character Approval: {character.key}",
                    status='OPEN'
                )

                for job in jobs:
                    # Add approval comment
                    comment_text = f"Character APPROVED by {self.caller.key}"
                    if message:
                        comment_text += f"\n\nStaff message: {message}"

                    Comment.objects.create(
                        job=job,
                        author=self.caller.account,
                        content=comment_text
                    )

                    # Close the job
                    job.status = 'CLOSED'
                    job.save()

                    self.caller.msg(f"|gJob #{job.sequence_number} closed.|n")
            except Exception as e:
                # Don't fail approval if Jobs integration has issues
                self.caller.msg(f"|yWarning:|n Could not update related Job: {e}")


class CmdReject(Command):
    """
    Reject a character application.

    Usage:
        +reject <character>=<reason>

    Rejects a character, keeping them in pending status but notifying
    the player of issues that need to be addressed. A reason MUST be
    provided explaining why the character was rejected.

    Examples:
        +reject John=Skills exceed allowed limits. Please review chargen rules.
        +reject Mary=Clan choice doesn't match concept. Please revise.
    """

    key = "+reject"
    aliases = ["reject"]
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "Staff"

    def func(self):
        """Reject a character."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +reject <character>=<reason>")
            self.caller.msg("|rYou must provide a reason for rejection.|n")
            return

        # Parse arguments
        try:
            char_name, reason = self.args.split('=', 1)
            char_name = char_name.strip()
            reason = reason.strip()
        except ValueError:
            self.caller.msg("Usage: +reject <character>=<reason>")
            return

        if not reason:
            self.caller.msg("|rYou must provide a reason for rejection.|n")
            return

        # Find character
        results = object_search(char_name, typeclass="typeclasses.characters.Character")
        
        if not results:
            self.caller.msg(f"|rCharacter '{char_name}' not found.|n")
            return
        
        if len(results) > 1:
            self.caller.msg("|rMultiple characters found. Please be more specific.|n")
            return

        character = results[0]

        # Get or create bio
        bio, created = CharacterBio.objects.get_or_create(character=character)

        # Update status and rejection tracking on the model
        bio.status = 'rejected'
        bio.rejection_notes = reason
        bio.rejection_count += 1
        bio.save()

        # Notify staff
        self.caller.msg(f"|yCharacter '{character.key}' has been rejected.|n")

        # Notify player (stores for offline delivery and sends immediately if online)
        if character.account:
            msg = f"Your character '{character.key}' requires revisions.\n"
            msg += f"Staff feedback from {self.caller.key}:\n{reason}\n"
            msg += "Please edit and resubmit via the character creation page."
            notify_account(character.account, msg, notification_type="rejection")

        # Log the rejection
        if not hasattr(character.db, 'staff_actions'):
            character.db.staff_actions = []

        character.db.staff_actions.append({
            'action': 'rejected',
            'staff': self.caller.key,
            'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'reason': reason
        })

        # Add rejection comment to related Job in Jobs system
        if JOBS_AVAILABLE:
            try:
                # Find Job for this character (created during +chargen/finalize)
                jobs = Job.objects.filter(
                    title__icontains=f"Character Approval: {character.key}",
                    status='OPEN'
                )

                for job in jobs:
                    # Add rejection comment
                    comment_text = f"Character requires revisions - feedback provided by {self.caller.key}:\n\n{reason}\n\nCharacter remains pending. Player has been notified to make changes and resubmit."

                    Comment.objects.create(
                        job=job,
                        author=self.caller.account,
                        content=comment_text
                    )

                    # Keep job OPEN for resubmission
                    self.caller.msg(f"|yJob #{job.sequence_number} updated with rejection feedback (remains open).|n")
            except Exception as e:
                # Don't fail rejection if Jobs integration has issues
                self.caller.msg(f"|yWarning:|n Could not update related Job: {e}")


class CmdImportCharacter(Command):
    """
    Import character data from a JSON file.

    Usage:
        +import <filename>

    Imports character traits, specialties, and bio information from a JSON
    file in the server/conf/character_imports/ directory. This is intended
    for importing characters created via the web character generator.

    The JSON file must be placed in: server/conf/character_imports/

    Only the character you are currently puppeting can be imported to.

    Examples:
        +import mycharacter.json
        +import john_brujah.json
    """

    key = "+import"
    aliases = ["import"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Import character from JSON file."""
        if not self.args:
            self.caller.msg("Usage: +import <filename>")
            self.caller.msg("Files must be placed in server/conf/character_imports/")
            return

        # Get the filename
        filename = self.args.strip()
        
        # Add .json extension if not provided
        if not filename.endswith('.json'):
            filename += '.json'

        # Security: prevent directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            self.caller.msg("|rInvalid filename. Only use simple filenames without path separators.|n")
            return

        # Build the full path
        import_dir = os.path.join(settings.GAME_DIR, 'server', 'conf', 'character_imports')
        filepath = os.path.join(import_dir, filename)

        # Check if file exists
        if not os.path.exists(filepath):
            self.caller.msg(f"|rFile '{filename}' not found in character_imports directory.|n")
            self.caller.msg(f"|yPlace your JSON file in: {import_dir}|n")
            return

        # Check if caller is puppeting a character
        if not self.caller.has_account:
            self.caller.msg("|rYou must be puppeting a character to import data.|n")
            return

        character = self.caller

        # Load and parse the JSON file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except json.JSONDecodeError as e:
            self.caller.msg(f"|rError parsing JSON file: {e}|n")
            return
        except Exception as e:
            self.caller.msg(f"|rError reading file: {e}|n")
            return

        # Validate the JSON structure
        if not isinstance(json_data, dict):
            self.caller.msg("|rInvalid JSON format. Expected a dictionary/object.|n")
            return

        # Perform the import
        self.caller.msg("|wImporting character data...|n")
        
        try:
            results = enhanced_import_character_from_json(character, json_data, validate_only=False)
        except Exception as e:
            self.caller.msg(f"|rError during import: {e}|n")
            return

        # Display results
        output = []
        output.append("|w" + "=" * 78 + "|n")
        output.append("|wCharacter Import Results|n")
        output.append("|w" + "=" * 78 + "|n")
        
        if results['success']:
            output.append("|gImport completed successfully!|n")
            output.append("")
            output.append(f"  Traits imported: |c{results['imported_traits']}|n")
            output.append(f"  Specialties imported: |c{results['imported_specialties']}|n")
            output.append(f"  Powers imported: |c{results['imported_powers']}|n")
        else:
            output.append("|yImport completed with issues.|n")
            output.append("")
            output.append(f"  Traits imported: |c{results['imported_traits']}|n")
            output.append(f"  Specialties imported: |c{results['imported_specialties']}|n")
            output.append(f"  Powers imported: |c{results['imported_powers']}|n")

        # Show validation errors if any
        if results['validation_errors']:
            output.append("")
            output.append("|yValidation Errors:|n")
            for error in results['validation_errors']:
                output.append(f"  |y- {error}|n")

        # Show import errors if any
        if results['errors']:
            output.append("")
            output.append("|rImport Errors:|n")
            for error in results['errors']:
                output.append(f"  |r- {error}|n")

        # Show warnings if any
        if results['warnings']:
            output.append("")
            output.append("|yWarnings:|n")
            for warning in results['warnings']:
                output.append(f"  |y- {warning}|n")

        output.append("|w" + "=" * 78 + "|n")
        
        self.caller.msg("\n".join(output))


class ChargenCmdSet(CmdSet):
    """
    Command set for character generation and staff approval commands.
    """

    key = "ChargenCmdSet"

    def at_cmdset_creation(self):
        """Add commands to the set."""
        # Staff approval commands
        self.add(CmdPending())
        self.add(CmdReview())
        self.add(CmdCharEdit())
        self.add(CmdApprove())
        self.add(CmdReject())
        self.add(CmdImportCharacter())

        # Player character creation commands (V5 system)
        from commands.v5.chargen import CmdChargen, CmdSetStat, CmdSetDiscipline
        self.add(CmdChargen())
        self.add(CmdSetStat())
        self.add(CmdSetDiscipline())
