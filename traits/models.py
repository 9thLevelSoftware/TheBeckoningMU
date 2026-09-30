"""
VtM 5e Trait System Models - Database-driven replacement for world/data.py hardcoded traits.
Provides comprehensive character sheet functionality for Vampire: The Masquerade 5th Edition.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from evennia.objects.models import ObjectDB


class TraitCategory(models.Model):
    """
    Defines the major categories of traits in VtM 5e.
    """
    name = models.CharField(max_length=50, unique=True, help_text="Category name (e.g., 'Attributes', 'Skills', 'Disciplines')")
    code = models.CharField(max_length=20, unique=True, help_text="Short code for internal use (e.g., 'attributes', 'skills')")
    description = models.TextField(blank=True, help_text="Description of this trait category")
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order for this category")

    class Meta:
        app_label = 'traits'
        ordering = ['sort_order', 'name']
        verbose_name_plural = "Trait Categories"

    def __str__(self):
        return self.name


class Trait(models.Model):
    """
    Defines a single trait in the VtM 5e system.
    Can be an Attribute, Skill, Discipline, Advantage, Flaw, etc.
    """
    name = models.CharField(max_length=100, unique=True, help_text="The name of the trait")
    category = models.ForeignKey(TraitCategory, on_delete=models.CASCADE, related_name='traits')
    description = models.TextField(blank=True, help_text="In-game description for the trait")

    # Trait configuration
    is_instanced = models.BooleanField(default=False, help_text="Can this trait be taken multiple times with different focuses? (e.g., Allies, Contacts)")
    has_specialties = models.BooleanField(default=False, help_text="Can this trait have specialties? (e.g., Skills, some Advantages)")

    # VtM 5e specific fields
    splat_restriction = models.CharField(max_length=50, blank=True, null=True, help_text="Restricts trait to specific character type (e.g., 'vampire', 'ghoul')")
    min_value = models.PositiveSmallIntegerField(default=0, help_text="Minimum rating for this trait")
    max_value = models.PositiveSmallIntegerField(default=5, help_text="Maximum rating for this trait")

    # Display and organization
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order within category")
    is_active = models.BooleanField(default=True, help_text="Is this trait currently available for use?")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'traits'
        ordering = ['category__sort_order', 'sort_order', 'name']
        unique_together = ['name', 'category']

    def __str__(self):
        return f"{self.category.name}: {self.name}"

    @property
    def full_name(self):
        """Returns category and name for display."""
        return f"{self.category.name} - {self.name}"


class TraitValue(models.Model):
    """
    Defines valid values/ratings for specific traits.
    Allows flexible configuration of what ratings are valid for each trait.
    """
    trait = models.ForeignKey(Trait, on_delete=models.CASCADE, related_name='valid_values')
    value = models.IntegerField(help_text="Valid rating/value for this trait")
    cost = models.PositiveIntegerField(default=1, help_text="XP cost to purchase this level (if applicable)")
    description = models.CharField(max_length=200, blank=True, help_text="Description of this rating level")

    class Meta:
        app_label = 'traits'
        unique_together = ['trait', 'value']
        ordering = ['trait', 'value']

    def __str__(self):
        return f"{self.trait.name} {self.value}"


class DisciplinePower(models.Model):
    """
    Defines specific powers within VtM 5e Disciplines.
    """
    name = models.CharField(max_length=100, unique=True, help_text="Name of the discipline power")
    discipline = models.ForeignKey(Trait, on_delete=models.CASCADE, related_name='powers',
                                  limit_choices_to={'category__code': 'disciplines'})
    level = models.PositiveSmallIntegerField(help_text="Discipline level required to learn this power")
    description = models.TextField(help_text="Complete description of the power's effects")

    # Amalgam power support
    amalgam_discipline = models.ForeignKey(Trait, on_delete=models.SET_NULL, blank=True, null=True,
                                          related_name='amalgam_powers',
                                          limit_choices_to={'category__code': 'disciplines'},
                                          help_text="Required secondary discipline for Amalgam powers")
    amalgam_level = models.PositiveSmallIntegerField(blank=True, null=True,
                                                   help_text="Required level in secondary discipline")

    # System information
    dice_pool = models.CharField(max_length=100, blank=True, help_text="Dice pool for this power (e.g., 'Resolve + Auspex')")
    cost = models.CharField(max_length=50, blank=True, help_text="Blood cost or other requirements")
    duration = models.CharField(max_length=100, blank=True, help_text="How long the power lasts")

    # Metadata
    sort_order = models.PositiveIntegerField(default=0, help_text="Display order within discipline level")
    is_active = models.BooleanField(default=True, help_text="Is this power currently available?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'traits'
        ordering = ['discipline', 'level', 'sort_order', 'name']
        unique_together = ['discipline', 'name']

    def __str__(self):
        amalgam_str = f" (Amalgam: {self.amalgam_discipline.name} {self.amalgam_level})" if self.amalgam_discipline else ""
        return f"{self.discipline.name} {self.level}: {self.name}{amalgam_str}"

    @property
    def requirements_text(self):
        """Returns human-readable requirements text."""
        req = f"{self.discipline.name} {self.level}"
        if self.amalgam_discipline:
            req += f", {self.amalgam_discipline.name} {self.amalgam_level}"
        return req


class CharacterTrait(models.Model):
    """
    Links a Character to a Trait, storing their rating and specialty information.
    This is the core model for character sheets.
    """
    character = models.ForeignKey(ObjectDB, on_delete=models.CASCADE, related_name='character_traits')
    trait = models.ForeignKey(Trait, on_delete=models.CASCADE, related_name='character_assignments')
    rating = models.PositiveSmallIntegerField(default=0, help_text="Character's rating in this trait")

    # For instanced traits (e.g., "Allies: Police Department")
    instance_name = models.CharField(max_length=100, blank=True, null=True,
                                   help_text="Specific instance of this trait (for instanced traits)")

    # For skill specialties (e.g., "Firearms (Pistols)")
    specialty = models.CharField(max_length=100, blank=True, null=True,
                               help_text="Specialty within this trait (for skills and some advantages)")

    # XP tracking
    xp_spent = models.PositiveIntegerField(default=0, help_text="Total XP spent on this trait")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'traits'
        # A character can have the same trait multiple times if it's instanced or has different specialties
        unique_together = ['character', 'trait', 'instance_name', 'specialty']
        ordering = ['trait__category__sort_order', 'trait__sort_order', 'trait__name']

    def __str__(self):
        base = f"{self.character.db_key}: {self.trait.name} {self.rating}"

        if self.instance_name:
            base += f" ({self.instance_name})"

        if self.specialty:
            base += f" [{self.specialty}]"

        return base

    @property
    def display_name(self):
        """Returns formatted display name for this trait assignment."""
        name = self.trait.name

        if self.instance_name:
            name += f" ({self.instance_name})"

        if self.specialty:
            name += f" [{self.specialty}]"

        return name

    def clean(self):
        """Validate trait assignment."""
        from django.core.exceptions import ValidationError

        # Check if rating is within valid range
        if self.rating < self.trait.min_value:
            raise ValidationError(f"Rating {self.rating} is below minimum {self.trait.min_value} for {self.trait.name}")

        if self.rating > self.trait.max_value:
            raise ValidationError(f"Rating {self.rating} exceeds maximum {self.trait.max_value} for {self.trait.name}")

        # Check if instance name is provided for instanced traits
        if self.trait.is_instanced and not self.instance_name:
            raise ValidationError(f"{self.trait.name} is an instanced trait and requires an instance name")

        # Check if instance name is provided for non-instanced traits
        if not self.trait.is_instanced and self.instance_name:
            raise ValidationError(f"{self.trait.name} is not an instanced trait and should not have an instance name")


class CharacterPower(models.Model):
    """
    Tracks which specific Discipline Powers a character has learned.
    """
    character = models.ForeignKey(ObjectDB, on_delete=models.CASCADE, related_name='character_powers')
    power = models.ForeignKey(DisciplinePower, on_delete=models.CASCADE, related_name='character_assignments')

    # XP tracking
    xp_spent = models.PositiveIntegerField(default=0, help_text="XP spent to learn this power")

    # Learning information
    learned_at = models.DateTimeField(auto_now_add=True, help_text="When this power was learned")
    teacher = models.ForeignKey(ObjectDB, on_delete=models.SET_NULL, blank=True, null=True,
                               related_name='taught_powers', help_text="Who taught this power (if applicable)")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'traits'
        unique_together = ['character', 'power']
        ordering = ['power__discipline', 'power__level', 'power__name']

    def __str__(self):
        return f"{self.character.db_key} knows {self.power.name}"

    def clean(self):
        """Validate power learning requirements."""
        from django.core.exceptions import ValidationError

        # Check if character has required discipline level
        try:
            discipline_trait = CharacterTrait.objects.get(
                character=self.character,
                trait=self.power.discipline
            )
            if discipline_trait.rating < self.power.level:
                raise ValidationError(f"Character needs {self.power.discipline.name} {self.power.level} to learn {self.power.name}")
        except CharacterTrait.DoesNotExist:
            raise ValidationError(f"Character must have {self.power.discipline.name} to learn {self.power.name}")

        # Check amalgam requirements
        if self.power.amalgam_discipline:
            try:
                amalgam_trait = CharacterTrait.objects.get(
                    character=self.character,
                    trait=self.power.amalgam_discipline
                )
                if amalgam_trait.rating < self.power.amalgam_level:
                    raise ValidationError(f"Character needs {self.power.amalgam_discipline.name} {self.power.amalgam_level} for {self.power.name}")
            except CharacterTrait.DoesNotExist:
                raise ValidationError(f"Character must have {self.power.amalgam_discipline.name} for {self.power.name}")


class TraitPrerequisite(models.Model):
    """
    Defines prerequisites for taking specific traits.
    Allows complex validation rules based on character state.
    """
    trait = models.ForeignKey(Trait, on_delete=models.CASCADE, related_name='prerequisites')

    # Prerequisite trait requirements
    required_trait = models.ForeignKey(Trait, on_delete=models.CASCADE, related_name='enables_traits',
                                     help_text="Required trait")
    required_rating = models.PositiveSmallIntegerField(default=1, help_text="Minimum required rating")
    required_instance = models.CharField(max_length=100, blank=True, null=True,
                                       help_text="Required instance (for instanced traits)")

    # Splat requirements
    required_splat = models.CharField(max_length=50, blank=True, null=True,
                                    help_text="Required character type (e.g., 'vampire')")

    # Custom validation function name (for complex rules)
    validation_function = models.CharField(max_length=100, blank=True, null=True,
                                         help_text="Name of custom validation function")

    # Error message
    error_message = models.CharField(max_length=200, default="Prerequisites not met",
                                   help_text="Message to show when prerequisite fails")

    class Meta:
        app_label = 'traits'
        ordering = ['trait', 'required_trait']

    def __str__(self):
        return f"{self.trait.name} requires {self.required_trait.name} {self.required_rating}"


class CharacterBio(models.Model):
    """
    Stores character background information specific to VtM 5e.
    """
    character = models.OneToOneField(ObjectDB, on_delete=models.CASCADE, related_name='vtm_bio')

    # Core VtM 5e background
    full_name = models.CharField(max_length=200, blank=True, help_text="Character's full name")
    concept = models.CharField(max_length=100, blank=True, help_text="Character concept")
    ambition = models.TextField(blank=True, help_text="Character's driving ambition")
    desire = models.TextField(blank=True, help_text="Character's immediate desire")

    # Vampire-specific fields
    clan = models.CharField(max_length=50, blank=True, help_text="Vampire clan")
    sire = models.CharField(max_length=100, blank=True, help_text="Character's sire")
    generation = models.PositiveSmallIntegerField(blank=True, null=True, help_text="Vampire generation")
    predator_type = models.CharField(max_length=50, blank=True, help_text="Predator type")

    # Character type
    splat = models.CharField(max_length=20, default='mortal', help_text="Character type (vampire, ghoul, mortal)")

    # Status lifecycle
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('rejected', 'Rejected'),
        ('approved', 'Approved'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='submitted',
        help_text="Current approval status"
    )
    background = models.TextField(
        blank=True,
        help_text="Character's backstory/background narrative"
    )
    rejection_notes = models.TextField(
        blank=True,
        help_text="Staff feedback on why character was rejected"
    )
    rejection_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this character has been rejected"
    )

    # Approval tracking
    approved_by = models.CharField(max_length=100, blank=True, help_text="Who approved this character")
    approved_at = models.DateTimeField(blank=True, null=True, help_text="When was this character approved")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'traits'

    def __str__(self):
        return f"{self.character.db_key}'s Bio ({self.splat})"

    @property
    def is_vampire(self):
        return self.splat == 'vampire'

    @property
    def is_ghoul(self):
        return self.splat == 'ghoul'

    @property
    def is_mortal(self):
        return self.splat == 'mortal'

    @property
    def approved(self):
        """Backward compatibility: returns True if status is 'approved'."""
        return self.status == 'approved'


class ExperienceTransaction(models.Model):
    """
    Tracks experience point spending and earning for characters.
    """
    character = models.ForeignKey(ObjectDB, on_delete=models.CASCADE, related_name='xp_transactions')

    # Transaction details
    amount = models.IntegerField(help_text="XP amount (positive for gained, negative for spent)")
    reason = models.CharField(max_length=200, help_text="Reason for this XP transaction")
    category = models.CharField(max_length=50, default='misc', help_text="Category of transaction")

    # Related objects (if XP was spent on something specific)
    related_trait = models.ForeignKey(CharacterTrait, on_delete=models.SET_NULL, blank=True, null=True,
                                    help_text="Trait this XP was spent on")
    related_power = models.ForeignKey(CharacterPower, on_delete=models.SET_NULL, blank=True, null=True,
                                    help_text="Power this XP was spent on")

    # Administrative
    approved_by = models.CharField(max_length=100, blank=True, help_text="Staff member who approved this transaction")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'traits'
        ordering = ['-created_at']

    def __str__(self):
        direction = "gained" if self.amount > 0 else "spent"
        return f"{self.character.db_key} {direction} {abs(self.amount)} XP: {self.reason}"
