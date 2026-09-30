"""
File-based help entries for TheBeckoningMU.

These complement command-based help and help entries added in the database
using the `sethelp` command in-game.

Control where Evennia reads these entries with `settings.FILE_HELP_ENTRY_MODULES`,
which is a list of python-paths to modules to read.

A module like this should hold a global `HELP_ENTRY_DICTS` list, containing
dicts that each represent a help entry.

Each dict is on the form:

    {'key': <str>,          # the help entry name
     'text': <str>,         # the actual help text
     'category': <str>,     # optional, otherwise settings.DEFAULT_HELP_CATEGORY
     'aliases': <list>,     # optional
     'locks': <str>}        # optional, 'view' controls seeing in help index

For TheBeckoningMU, we load text and YAML files from the `world/help` directory
and use those to populate the `HELP_ENTRY_DICTS`.

Files should have the following path structure:
    world/help/<category>/<name>.[txt,yaml,yml]

The <category> directory is optional. Top-level files will use the
`DEFAULT_HELP_CATEGORY` from Evennia settings.

Text files:
    Text files will simply be read verbatim as help file entries. They cannot
    specify other attributes such as aliases or locks. For that, use YAML files.

YAML files:
    The YAML file format is identical to the `HELP_ENTRY_DICTS` format described
    in the Evennia docs above. If the `key` is not specified, the file name will
    be used (same behavior as text files). If `category` is not specified, the
    directory name will be used (same behavior as text files).

    YAML files can also contain multiple documents, in which case each document
    represents a separate help entry.
"""

import os
from pathlib import Path
from django.conf import settings

# Try to import yaml; if not available, only text files will work
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Path to help files directory
HELP_FILES_DIR = Path(__file__).parent.joinpath("help").resolve()

# Default category for help files
DEFAULT_HELP_CATEGORY = getattr(settings, "DEFAULT_HELP_CATEGORY", None) or "General"

# List of help entry dictionaries
HELP_ENTRY_DICTS = []

# Walk through help directory and load all files
if HELP_FILES_DIR.exists():
    for dir_path, dirs, files in os.walk(HELP_FILES_DIR):
        dir_path = Path(dir_path)

        # Determine category based on directory
        if dir_path == HELP_FILES_DIR:
            category = DEFAULT_HELP_CATEGORY
        elif len(dirs) > 0:
            # Don't allow nested directories
            raise RuntimeError(
                f"Nested help file directories are not supported. "
                f"Found: {dir_path.joinpath(dirs[0])}"
            )
        else:
            category = dir_path.name.capitalize()

        # Skip examples directory if it exists
        if category.lower() == "examples":
            continue

        # Process each file in the directory
        for file_name in files:
            name, ext = os.path.splitext(file_name)
            file_path = dir_path.joinpath(file_name)

            with open(file_path, encoding='utf-8') as file:
                if ext in [".yml", ".yaml"] and YAML_AVAILABLE:
                    # Load one or more YAML documents from file
                    for help_entry in yaml.safe_load_all(file):
                        # "name" is synonym for "key"
                        if "name" in help_entry:
                            help_entry["key"] = help_entry["name"]

                        # Use file name if key not given
                        if "key" not in help_entry:
                            help_entry["key"] = name

                        # Use directory name if category not given
                        if "category" not in help_entry:
                            help_entry["category"] = category

                        HELP_ENTRY_DICTS.append(help_entry)

                else:
                    # Load as simple text file containing help text
                    help_entry = {
                        "key": name,
                        "aliases": [],
                        "category": category,
                        "text": file.read(),
                    }
                    HELP_ENTRY_DICTS.append(help_entry)
