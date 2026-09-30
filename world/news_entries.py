"""
File-based news entries for TheBeckoningMU.

News entries provide announcements, updates, policies, and game information
for players and staff.

Control where Evennia reads these entries with `settings.FILE_NEWS_ENTRY_MODULES`,
which is a list of python-paths to modules to read.

A module like this should hold a global `NEWS_ENTRY_DICTS` list, containing
dicts that each represent a news entry.

Each dict is on the form:

    {'key': <str>,          # the news entry name
     'text': <str>,         # the actual news text
     'category': <str>,     # optional, otherwise 'general'
     'aliases': <list>,     # optional
     'locks': <str>}        # optional, 'view' controls seeing in news index

For TheBeckoningMU, we load text and YAML files from the `world/news` directory
and use those to populate the `NEWS_ENTRY_DICTS`.

Files should have the following path structure:
    world/news/<category>/<name>.[txt,yaml,yml]

The <category> directory is optional. Top-level files will use 'General' category.

Text files:
    Text files will simply be read verbatim as news file entries. They cannot
    specify other attributes such as aliases or locks. For that, use YAML files.

YAML files:
    The YAML file format is identical to the `NEWS_ENTRY_DICTS` format described
    above. If the `key` is not specified, the file name will be used (same
    behavior as text files). If `category` is not specified, the directory name
    will be used (same behavior as text files).

    YAML files can also contain multiple documents, in which case each document
    represents a separate news entry.
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

# Path to news files directory
NEWS_FILES_DIR = Path(__file__).parent.joinpath("news").resolve()

# Default category for news files
DEFAULT_NEWS_CATEGORY = "General"

# List of news entry dictionaries
NEWS_ENTRY_DICTS = []

# Walk through news directory and load all files
if NEWS_FILES_DIR.exists():
    for dir_path, dirs, files in os.walk(NEWS_FILES_DIR):
        dir_path = Path(dir_path)

        # Determine category based on directory
        if dir_path == NEWS_FILES_DIR:
            category = DEFAULT_NEWS_CATEGORY
        elif len(dirs) > 0:
            # Don't allow nested directories
            raise RuntimeError(
                f"Nested news file directories are not supported. "
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
                    for news_entry in yaml.safe_load_all(file):
                        # "name" is synonym for "key"
                        if "name" in news_entry:
                            news_entry["key"] = news_entry["name"]

                        # Use file name if key not given
                        if "key" not in news_entry:
                            news_entry["key"] = name

                        # Use directory name if category not given
                        if "category" not in news_entry:
                            news_entry["category"] = category

                        NEWS_ENTRY_DICTS.append(news_entry)

                else:
                    # Load as simple text file containing news text
                    news_entry = {
                        "key": name,
                        "aliases": [],
                        "category": category,
                        "text": file.read(),
                    }
                    NEWS_ENTRY_DICTS.append(news_entry)
