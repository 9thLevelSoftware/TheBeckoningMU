"""
Django management command to seed VtM 5e trait data.

Populates the database with:
- Trait categories (Attributes, Skills, Disciplines, etc.)
- All V5 attributes (9 total)
- All V5 skills (27 total)
- All V5 disciplines (12 total)
- All discipline powers, backgrounds, merits and flaws (from world/v5_data.py)

Usage:
    evennia seed_traits [--clear]
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from traits.models import TraitCategory, Trait, DisciplinePower

# world/v5_data.py is the only source of rules data; this command copies it
# into the traits tables until PR 7 deletes them.
from world.v5_data import (
    ATTRIBUTES,
    BACKGROUNDS,
    DISCIPLINE_POWERS,
    DISCIPLINES,
    FLAWS,
    MERITS,
    SKILLS,
)


class Command(BaseCommand):
    """Seed VtM 5e trait definitions from V5_MECHANICS.md reference."""

    help = "Seed comprehensive V5 trait data (Attributes, Skills, Disciplines, Powers)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing trait data before seeding',
        )

    def handle(self, *args, **options):
        """Execute the command."""

        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing trait data...'))
            DisciplinePower.objects.all().delete()
            Trait.objects.all().delete()
            TraitCategory.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared all existing trait data'))

        with transaction.atomic():
            # Create trait categories
            categories = self._create_categories()
            self.stdout.write(self.style.SUCCESS(f'Created {len(categories)} trait categories'))

            # Create attributes
            attr_count = self._create_attributes(categories['attributes'])
            self.stdout.write(self.style.SUCCESS(f'Created {attr_count} attributes'))

            # Create skills
            skill_count = self._create_skills(categories['skills'])
            self.stdout.write(self.style.SUCCESS(f'Created {skill_count} skills'))

            # Create disciplines
            disc_count = self._create_disciplines(categories['disciplines'])
            self.stdout.write(self.style.SUCCESS(f'Created {disc_count} disciplines'))

            # Create discipline powers (sample set)
            power_count = self._create_discipline_powers()
            self.stdout.write(self.style.SUCCESS(f'Created {power_count} discipline powers'))

            # Create backgrounds, merits and flaws
            adv_count = self._create_advantages(categories['advantages'], categories['flaws'])
            self.stdout.write(self.style.SUCCESS(f'Created {adv_count} advantages and flaws'))

        self.stdout.write(self.style.SUCCESS('\n[SUCCESS] Trait seeding complete!'))

    def _create_categories(self):
        """Create trait categories."""
        categories_data = [
            {'name': 'Attributes', 'code': 'attributes', 'sort_order': 1,
             'description': 'Innate capabilities - Physical, Social, Mental'},
            {'name': 'Skills', 'code': 'skills', 'sort_order': 2,
             'description': 'Trained abilities and learned knowledge'},
            {'name': 'Disciplines', 'code': 'disciplines', 'sort_order': 3,
             'description': 'Supernatural powers fueled by vampiric blood'},
            {'name': 'Advantages', 'code': 'advantages', 'sort_order': 4,
             'description': 'Merits, backgrounds, and other benefits'},
            {'name': 'Flaws', 'code': 'flaws', 'sort_order': 5,
             'description': 'Disadvantages and complications'},
        ]

        categories = {}
        for cat_data in categories_data:
            cat, _ = TraitCategory.objects.get_or_create(
                code=cat_data['code'],
                defaults=cat_data
            )
            categories[cat_data['code']] = cat

        return categories

    def _create_attributes(self, category):
        """Create all V5 attributes from v5_data constants."""
        # Descriptions for each attribute (could also be moved to v5_data in future)
        attribute_descriptions = {
            'Strength': 'Physical power, muscle, brute force',
            'Dexterity': 'Agility, grace, reflexes, fine motor control',
            'Stamina': 'Endurance, resilience, toughness, constitution',
            'Charisma': 'Charm, magnetism, ability to inspire',
            'Manipulation': 'Ability to deceive, influence, control',
            'Composure': 'Self-control, grace under pressure, emotional regulation',
            'Intelligence': 'Reasoning, memory, analytical capability',
            'Wits': 'Cunning, quick thinking, situational awareness',
            'Resolve': 'Determination, focus, mental fortitude',
        }

        # Build attributes list from v5_data ATTRIBUTES constant
        # Order: Physical (1-3), Social (4-6), Mental (7-9)
        sort_order = 0
        count = 0

        for category_name in ['Physical', 'Social', 'Mental']:
            for attr_name in ATTRIBUTES[category_name]:
                sort_order += 1
                _, created = Trait.objects.get_or_create(
                    name=attr_name,
                    category=category,
                    defaults={
                        'description': attribute_descriptions.get(attr_name, ''),
                        'sort_order': sort_order,
                        'min_value': 1,  # All vampires have at least 1 in each attribute
                        'max_value': 5,
                        'has_specialties': False,
                        'is_instanced': False,
                    }
                )
                if created:
                    count += 1

        return count

    def _create_skills(self, category):
        """Create all V5 skills from v5_data constants."""
        # Descriptions for each skill (could also be moved to v5_data in future)
        skill_descriptions = {
            # Physical Skills
            'Athletics': 'Running, jumping, climbing, swimming, parkour',
            'Brawl': 'Unarmed combat, grappling, martial arts',
            'Craft': 'Creating and repairing physical objects',
            'Drive': 'Operating vehicles',
            'Firearms': 'Shooting guns of all types',
            'Larceny': 'Lock picking, pickpocketing, security',
            'Melee': 'Armed combat with melee weapons',
            'Stealth': 'Moving unseen and unheard',
            'Survival': 'Wilderness skills, tracking, foraging',
            # Social Skills
            'Animal Ken': 'Understanding and influencing animals',
            'Etiquette': 'Social graces, protocol, proper behavior',
            'Insight': 'Reading people, detecting lies, empathy',
            'Intimidation': 'Coercion through fear or threat',
            'Leadership': 'Inspiring and directing others',
            'Performance': 'Artistic expression, entertainment',
            'Persuasion': 'Convincing others through reason or charm',
            'Streetwise': 'Urban survival, criminal knowledge',
            'Subterfuge': 'Lying, disguise, misdirection',
            # Mental Skills
            'Academics': 'Scholarly knowledge, research, humanities',
            'Awareness': 'Noticing details, perception, alertness',
            'Finance': 'Money management, economics, business',
            'Investigation': 'Solving mysteries, gathering evidence',
            'Medicine': 'Medical knowledge, first aid, anatomy',
            'Occult': 'Supernatural lore, mysticism, rituals',
            'Politics': 'Government, power structures, diplomacy',
            'Science': 'Natural sciences, chemistry, biology',
            'Technology': 'Computers, electronics, modern tech',
        }

        # Build skills list from v5_data SKILLS constant
        # Order: Physical (1-9), Social (10-18), Mental (19-27)
        sort_order = 0
        count = 0

        for category_name in ['Physical', 'Social', 'Mental']:
            for skill_name in SKILLS[category_name]:
                sort_order += 1
                _, created = Trait.objects.get_or_create(
                    name=skill_name,
                    category=category,
                    defaults={
                        'description': skill_descriptions.get(skill_name, ''),
                        'sort_order': sort_order,
                        'min_value': 0,  # Skills can be untrained
                        'max_value': 5,
                        'has_specialties': True,  # All skills can have specialties
                        'is_instanced': False,
                    }
                )
                if created:
                    count += 1

        return count

    def _create_disciplines(self, category):
        """Create all V5 disciplines from v5_data constants."""
        # Build disciplines from v5_data DISCIPLINES constant
        # Sort alphabetically for consistent ordering
        count = 0
        sort_order = 0

        for disc_name in sorted(DISCIPLINES.keys()):
            disc_data = DISCIPLINES[disc_name]
            sort_order += 1

            # Determine splat restriction (Thin-Blood Alchemy is thin-blood only)
            splat_restriction = None
            if disc_data.get('type') == 'thin-blood':
                splat_restriction = 'thin-blood'

            defaults = {
                'description': disc_data.get('description', ''),
                'sort_order': sort_order,
                'min_value': 0,
                'max_value': 5,
                'has_specialties': False,
                'is_instanced': False,
                'splat_restriction': splat_restriction,
            }
            _, created = Trait.objects.get_or_create(
                name=disc_name,
                category=category,
                defaults=defaults
            )
            if created:
                count += 1

        return count

    def _create_discipline_powers(self):
        """Create every discipline power from v5_data.DISCIPLINE_POWERS."""
        disciplines = {d.name: d for d in Trait.objects.filter(category__code='disciplines')}

        count = 0
        for power in DISCIPLINE_POWERS.values():
            discipline = disciplines.get(power['discipline'])
            if not discipline:
                continue

            defaults = {
                'level': power['level'],
                'description': power.get('description') or '',
                'cost': 'One Rouse Check' if power.get('rouse') else 'Free',
                'dice_pool': power.get('dice_pool') or '',
                'duration': power.get('duration') or '',
            }

            # Amalgam requirement is stored in v5_data as e.g. "Obfuscate 2"
            if power.get('amalgam'):
                amalgam_name, _, amalgam_level = power['amalgam'].rpartition(' ')
                amalgam_disc = disciplines.get(amalgam_name)
                if amalgam_disc:
                    defaults['amalgam_discipline'] = amalgam_disc
                    defaults['amalgam_level'] = int(amalgam_level)

            _, created = DisciplinePower.objects.get_or_create(
                name=power['name'],
                discipline=discipline,
                defaults=defaults
            )
            if created:
                count += 1

        return count

    def _create_advantages(self, advantages_category, flaws_category):
        """Create backgrounds, merits and flaws from v5_data."""
        count = 0
        sort_order = 0
        for name, data in BACKGROUNDS.items():
            sort_order += 1
            _, created = Trait.objects.get_or_create(
                name=name,
                category=advantages_category,
                defaults={
                    'description': data.get('description', ''),
                    'sort_order': sort_order,
                    'min_value': 0,
                    'max_value': 5,
                    'is_instanced': bool(data.get('instanced')),
                },
            )
            count += int(created)
        for table, category in ((MERITS, advantages_category), (FLAWS, flaws_category)):
            for name, data in table.items():
                sort_order += 1
                _, created = Trait.objects.get_or_create(
                    name=name,
                    category=category,
                    defaults={
                        'description': data.get('description', ''),
                        'sort_order': sort_order,
                        'min_value': min(data['dots']),
                        'max_value': max(data['dots']),
                    },
                )
                count += int(created)
        return count
