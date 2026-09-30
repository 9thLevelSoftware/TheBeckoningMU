"""
Django management command to load VtM 5e trait data from JSON files.

Usage:
    evennia load_traits [--clear]
"""

from django.core.management.base import BaseCommand
from evennia.utils import logger
import json
from pathlib import Path
from traits.models import Trait, TraitCategory


class Command(BaseCommand):
    """Load VtM 5e trait definitions from JSON files."""

    help = "Load trait data (Skills, Disciplines, Attributes, etc.) from JSON files"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing trait data before loading',
        )

    def handle(self, *args, **options):
        """Execute the command."""

        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing trait data...'))
            count = Trait.objects.all().count()
            Trait.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} existing traits'))

        # Define data directory
        data_dir = Path(__file__).resolve().parent.parent.parent.parent / 'world' / 'vtm5e_data'

        if not data_dir.exists():
            self.stdout.write(
                self.style.ERROR(f'Data directory not found: {data_dir}')
            )
            self.stdout.write('Please create the directory and add JSON files.')
            return

        # Define trait data files
        trait_files = {
            'attributes': 'attributes.json',
            'skills': 'skills.json',
            'disciplines': 'disciplines.json',
            'advantages': 'advantages.json',
        }

        total_loaded = 0

        for category, filename in trait_files.items():
            filepath = data_dir / filename

            if not filepath.exists():
                self.stdout.write(
                    self.style.WARNING(f'Skipping {filename} (not found)')
                )
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Handle different JSON structures
                if isinstance(data, dict):
                    traits_list = data.get('traits', data.get(category, []))
                elif isinstance(data, list):
                    traits_list = data
                else:
                    self.stdout.write(
                        self.style.ERROR(f'Invalid JSON structure in {filename}')
                    )
                    continue

                # Get or create the trait category
                cat_obj, _ = TraitCategory.objects.get_or_create(
                    code=category,
                    defaults={'name': category.title()}
                )

                loaded = 0
                for trait_data in traits_list:
                    # Create or update trait
                    trait, created = Trait.objects.update_or_create(
                        name=trait_data.get('name'),
                        defaults={
                            'category': cat_obj,
                            'description': trait_data.get('description', ''),
                            'has_specialties': trait_data.get('has_specialties', False),
                            'is_instanced': trait_data.get('is_instanced', False),
                        }
                    )
                    loaded += 1
                    action = 'Created' if created else 'Updated'
                    if options['verbosity'] >= 2:
                        self.stdout.write(f'  {action}: {trait.name}')

                total_loaded += loaded
                self.stdout.write(
                    self.style.SUCCESS(f'Loaded {loaded} traits from {filename}')
                )

            except json.JSONDecodeError as e:
                self.stdout.write(
                    self.style.ERROR(f'Invalid JSON in {filename}: {e}')
                )
            except Exception as e:
                logger.log_err(f'Error loading {filename}: {e}')
                self.stdout.write(
                    self.style.ERROR(f'Error loading {filename}: {e}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\nTotal: Loaded {total_loaded} traits')
        )
