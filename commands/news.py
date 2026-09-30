"""
News command for TheBeckoningMU.

Allows players to read game news and announcements organized by category.
"""

from evennia import Command
from evennia import default_cmds
from django.conf import settings
import importlib


class CmdNews(Command):
    """
    Read game news and announcements

    Usage:
      news                       - List all news categories
      news <category>            - List news topics in a category
      news <category>/<topic>    - Read a specific news topic

    Examples:
      news                       - Show all categories (general, updates, policy)
      news general               - List all general news topics
      news general/welcome       - Read the welcome news file
      news updates               - List update announcements
      news policy/rules          - Read game rules

    News provides important information about the game including:
    - General information and getting started guides
    - Updates and changes to the game
    - Policies and rules

    You can also use 'news' like the help command for quick reference.
    """

    key = "news"
    aliases = ["+news"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        """Execute the news command."""

        # Load news entries from configured modules
        news_entries = self._load_news_entries()

        if not news_entries:
            self.caller.msg("|rNo news entries are currently available.|n")
            return

        # Parse arguments
        if not self.args.strip():
            # No arguments - show categories
            self._show_categories(news_entries)
            return

        # Split argument by / to get category and topic
        parts = self.args.strip().lower().split('/', 1)
        category = parts[0]
        topic = parts[1] if len(parts) > 1 else None

        if topic:
            # Show specific news entry
            self._show_news_entry(news_entries, category, topic)
        else:
            # Show topics in category
            self._show_topics_in_category(news_entries, category)

    def _load_news_entries(self):
        """Load news entries from configured modules."""
        news_modules = getattr(settings, 'FILE_NEWS_ENTRY_MODULES', [])

        all_entries = []
        for module_path in news_modules:
            try:
                module = importlib.import_module(module_path)
                entries = getattr(module, 'NEWS_ENTRY_DICTS', [])
                all_entries.extend(entries)
            except ImportError:
                continue
            except AttributeError:
                continue

        return all_entries

    def _show_categories(self, news_entries):
        """Show all available news categories."""
        # Get unique categories
        categories = {}
        for entry in news_entries:
            cat = entry.get('category', 'General')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(entry)

        # Build output
        msg = []
        msg.append("|w" + "=" * 70 + "|n")
        msg.append("|y                         NEWS CATEGORIES                            |n")
        msg.append("|w" + "=" * 70 + "|n")
        msg.append("")
        msg.append("Use |wnews <category>|n to see topics in that category.")
        msg.append("Use |wnews <category>/<topic>|n to read a specific news file.")
        msg.append("")

        for cat_name in sorted(categories.keys()):
            count = len(categories[cat_name])
            msg.append(f"  |c{cat_name.upper():15}|n - {count} topic{'s' if count != 1 else ''}")

        msg.append("")
        msg.append("|w" + "=" * 70 + "|n")

        self.caller.msg("\n".join(msg))

    def _show_topics_in_category(self, news_entries, category):
        """Show all topics in a specific category."""
        # Find entries in this category
        matching_entries = [
            e for e in news_entries
            if e.get('category', 'General').lower() == category.lower()
        ]

        if not matching_entries:
            self.caller.msg(f"|rNo news category '{category}' found.|n")
            self.caller.msg("Use |wnews|n to see all available categories.")
            return

        # Build output
        msg = []
        cat_title = matching_entries[0].get('category', 'General')
        msg.append("|w" + "=" * 70 + "|n")
        msg.append(f"|y                   NEWS - {cat_title.upper()}                   |n")
        msg.append("|w" + "=" * 70 + "|n")
        msg.append("")
        msg.append(f"Use |wnews {category}/<topic>|n to read a specific news file.")
        msg.append("")

        for entry in sorted(matching_entries, key=lambda e: e.get('key', '')):
            key = entry.get('key', 'unknown')
            aliases_list = entry.get('aliases', [])
            alias_str = f" (aliases: {', '.join(aliases_list)})" if aliases_list else ""
            msg.append(f"  |w{key}|n{alias_str}")

        msg.append("")
        msg.append("|w" + "=" * 70 + "|n")

        self.caller.msg("\n".join(msg))

    def _show_news_entry(self, news_entries, category, topic):
        """Show a specific news entry."""
        # Find the entry
        matching_entry = None
        for entry in news_entries:
            entry_cat = entry.get('category', 'General').lower()
            entry_key = entry.get('key', '').lower()
            entry_aliases = [a.lower() for a in entry.get('aliases', [])]

            if entry_cat == category.lower():
                if entry_key == topic.lower() or topic.lower() in entry_aliases:
                    matching_entry = entry
                    break

        if not matching_entry:
            self.caller.msg(f"|rNo news topic '{topic}' found in category '{category}'.|n")
            self.caller.msg(f"Use |wnews {category}|n to see available topics in this category.")
            return

        # Display the news entry
        text = matching_entry.get('text', '|rNo text available for this news entry.|n')

        # Add header
        msg = []
        msg.append("")
        msg.append("|w" + "=" * 70 + "|n")
        cat_name = matching_entry.get('category', 'General')
        key_name = matching_entry.get('key', 'unknown')
        msg.append(f"|y  NEWS: {cat_name}/{key_name}|n")
        msg.append("|w" + "=" * 70 + "|n")
        msg.append("")
        msg.append(text)
        msg.append("")
        msg.append("|w" + "=" * 70 + "|n")

        self.caller.msg("\n".join(msg))


# For backwards compatibility with Evennia's help system
class CmdNews2(default_cmds.CmdHelp):
    """
    Alternative news command using Evennia's default help system.
    This is a fallback in case the file-based system isn't set up.
    """

    key = "news2"
    aliases = []
    help_category = "General"
    locks = "cmd:all()"

    def func(self):
        """Redirect to help system."""
        self.caller.msg("|yNote: Using fallback news system. File-based news not configured.|n")
        super().func()
