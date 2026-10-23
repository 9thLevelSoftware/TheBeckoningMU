"""
Help and news files describe commands that exist.

The file-based help (world/help) and news (world/news) are plain text, so
nothing ties them to the code. These tests do:

- every `+word`, `@word` and `word/switch` token is a command's key or alias
  as the help index shows it (and the switches are ones that command
  handles). Evennia's parser would also accept `+who` for `who`, but the
  files should teach the real name;
- every `help <topic>` / `news <topic>` names a topic;
- no help file has the same key as a command, which would hide the file
  behind the command's docstring (file guides use a `-guide` suffix);
- every command added in commands/default_cmdsets.py is still in the cmdset
  after merging, so nothing documented is silently shadowed;
- no Markdown is left (Evennia shows `**`, `#` and backticks literally).

A "token resolves" check can't see an instruction that names a real command
the reader isn't allowed to use, so a few of those are pinned by hand
(`KnownWrongInstructionTests`).
"""

import ast
import importlib
import inspect
import re
from functools import cache
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from evennia.commands.cmdset import CmdSet
from evennia.commands.default.help import CmdHelp
from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest

import commands.default_cmdsets as default_cmdsets
from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet, SessionCmdSet
from world.help_entries import HELP_ENTRY_DICTS
from world.news_entries import NEWS_ENTRY_DICTS

ROOT = Path(__file__).resolve().parent.parent
PREFIXES = settings.CMD_IGNORE_PREFIXES
# Docstrings of commands from these modules are checked too (Evennia's own
# docstrings are not ours to fix).
GAME_MODULES = ("commands.", "dice.", "bbs.", "jobs.", "boons.", "status.")

# `+word`, `@word` with optional /switches. Not after a word character or
# another token character, so "e-mail@host" and "+5" don't count.
PREFIXED = re.compile(r"(?<![\w@+/.\-'])([+@][A-Za-z][\w\-]*(?:/[A-Za-z][\w\-]*)*)")
# `word/switch` without a prefix; only checked when `word` is a lower-case
# command name ("Strength/Dexterity" and "and/or" are prose).
SWITCHED = re.compile(r"(?<![\w@+/.\-<\[])([a-z][\w\-]*(?:/[A-Za-z][\w\-]*)+)")
# `help X` / `news X` (news takes `<category>` or `<category>/<topic>`).
# English uses of the words are skipped by PROSE.
TOPIC_REF = re.compile(r"\b(help|news)\s+([+@]?[A-Za-z][\w\-]*(?:/[\w\-]+)?)")
PROSE = {
    "a",
    "an",
    "and",
    "any",
    "anyone",
    "categories",
    "command",
    "entries",
    "file",
    "files",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "me",
    "on",
    "or",
    "others",
    "out",
    "players",
    "someone",
    "the",
    "them",
    "this",
    "to",
    "topic",
    "topics",
    "us",
    "when",
    "with",
    "you",
    "your",
}
MARKDOWN = re.compile(
    r"\*\*|`|^\s*#{1,6}\s"  # bold, code, headings
    r"|\[[^\]]+\]\([^)]+\)"  # [links](url)
    r"|(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*])",  # *emphasis*
    re.MULTILINE,
)


def _no_prefix(name):
    name = name.lower()
    return name[1:] if name and name[0] in PREFIXES else name


@cache
def command_index():
    """{lowercase key or alias: command instance} for every logged-in cmdset."""
    index = {}
    for cmdset_class in (CharacterCmdSet, AccountCmdSet, SessionCmdSet):
        cmdset = cmdset_class()
        cmdset.at_cmdset_creation()
        for cmd in cmdset.commands:
            for name in (cmd.key, *cmd.aliases):
                index.setdefault(name.lower(), cmd)
    return index


@cache
def _source(cmd_class):
    try:
        return inspect.getsource(cmd_class)
    except (OSError, TypeError):
        return ""


_LITERAL = re.compile(r"""["']([A-Za-z][\w\-]*)["']""")


@cache
def _switch_literals(cmd_class):
    """
    String literals the class compares its switches against: those on a line
    that mentions `switch` ('"x" in self.switches', 'switch == "x"',
    'if switch in ("a", "b")'), not every string in the code.
    """
    names = set()
    for line in _source(cmd_class).splitlines():
        if "switch" in line:
            names.update(lit.lower() for lit in _LITERAL.findall(line))
    return names


def _handles_switch(cmd, switch):
    """True if `cmd` accepts `/switch` (its switch_options, else a literal it tests switches against)."""
    switch = switch.lower()
    options = getattr(cmd, "switch_options", None)
    if options:
        return switch in [opt.lower() for opt in options]
    return switch in _switch_literals(type(cmd))


def resolve_token(token):
    """
    Check a `+cmd/sw1/sw2` style token against the real command names.

    Returns:
        None if it resolves, else a reason string.
    """
    index = command_index()
    parts = token.split("/")
    # A command key may itself contain a switch ("job/claim", "+bucket/create").
    for cut in range(len(parts), 0, -1):
        cmd = index.get("/".join(parts[:cut]).lower())
        if cmd is not None:
            for switch in parts[cut:]:
                if not _handles_switch(cmd, switch):
                    return f"{cmd.key} has no /{switch} switch"
            return None
    return "no such command"


def command_for(token):
    """The command a `+cmd/sw` token names, or None."""
    index = command_index()
    parts = token.split("/")
    for cut in range(len(parts), 0, -1):
        cmd = index.get("/".join(parts[:cut]).lower())
        if cmd is not None:
            return cmd
    return None


def player_tokens():
    """(entry key, command) for every command token in help/news a player can read."""
    index = command_index()
    for entry in [*HELP_ENTRY_DICTS, *NEWS_ENTRY_DICTS]:
        if "perm(" in (entry.get("locks", "") or ""):
            continue
        text = strip_ansi(entry["text"])
        tokens = set(PREFIXED.findall(text))
        tokens |= {t for t in SWITCHED.findall(text) if t.split("/")[0] in index}
        for token in sorted(tokens):
            cmd = command_for(token)
            if cmd is not None:
                yield entry["key"], token, cmd


@cache
def topic_index():
    """Every name `help <x>` finds: commands (with or without prefix), file keys, categories."""
    names = set(command_index())
    names |= {_no_prefix(name) for name in command_index()}
    for entry in HELP_ENTRY_DICTS:
        names.add(entry["key"].lower())
        names.update(alias.lower() for alias in entry.get("aliases", []) or [])
        names.add(entry.get("category", "").lower())
    for cmd in command_index().values():
        names.add(cmd.help_category.lower())
    return names


@cache
def news_index():
    """What `news <x>` finds (commands/news.py): `<category>` or `<category>/<key>`."""
    names = set()
    for entry in NEWS_ENTRY_DICTS:
        category = entry.get("category", "General").lower()
        names.add(category)
        names.add(f"{category}/{entry['key'].lower()}")
    return names


def all_entries():
    """(label, raw text) for every help and news file entry and game command docstring."""
    for entry in HELP_ENTRY_DICTS:
        yield f"help {entry['key']}", entry["text"]
    for entry in NEWS_ENTRY_DICTS:
        yield f"news {entry['key']}", entry["text"]
    seen = set()
    for cmd in command_index().values():
        cmd_class = type(cmd)
        if cmd_class in seen or not cmd_class.__module__.startswith(GAME_MODULES):
            continue
        seen.add(cmd_class)
        yield f"command {cmd.key}", cmd_class.__doc__ or ""


def dangling_references():
    """Every unresolved command, switch or topic reference, as strings."""
    problems = []
    index = command_index()
    for label, raw in all_entries():
        text = strip_ansi(raw)
        tokens = set(PREFIXED.findall(text))
        tokens |= {t for t in SWITCHED.findall(text) if t.split("/")[0] in index}
        for token in sorted(tokens):
            reason = resolve_token(token)
            if reason:
                problems.append(f"{label}: {token} ({reason})")
        for kind, topic in sorted(set(TOPIC_REF.findall(text))):
            if topic.lower() in PROSE:
                continue
            topics = topic_index() if kind == "help" else news_index()
            if topic.lower() not in topics:
                problems.append(f"{label}: {kind} {topic} (no such topic)")
    return problems


def shadowed_entries():
    """File help keys or aliases that equal a command key or alias (ignoring prefixes)."""
    command_names = {_no_prefix(name) for name in command_index()}
    problems = []
    for entry in HELP_ENTRY_DICTS:
        for name in (entry["key"], *(entry.get("aliases", []) or [])):
            if _no_prefix(name) in command_names:
                problems.append(f"help file '{entry['key']}' is hidden by command '{name}'")
    return problems


def _added_commands():
    """
    {cmdset class name: [command classes]} for every `self.add(Name)` in
    commands/default_cmdsets.py, resolved through the imports in that class.
    """
    tree = ast.parse((ROOT / "commands" / "default_cmdsets.py").read_text(encoding="utf-8"))
    added = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        imports = {}
        names = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                for alias in sub.names:
                    imports[alias.asname or alias.name] = (sub.module, alias.name)
            elif (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "add"
                and sub.args
                and isinstance(sub.args[0], ast.Name)
            ):
                names.append(sub.args[0].id)
        classes = []
        for name in names:
            module, attr = imports[name]
            obj = getattr(importlib.import_module(module), attr)
            if inspect.isclass(obj) and issubclass(obj, CmdSet):
                cmdset = obj()
                cmdset.at_cmdset_creation()
                classes.extend(type(cmd) for cmd in cmdset.commands)
            else:
                classes.append(obj)
        added[node.name] = classes
    return added


class HelpReferenceTests(SimpleTestCase):
    def test_every_reference_resolves(self):
        problems = dangling_references()
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_command_docstrings_are_scanned(self):
        labels = [label for label, _text in all_entries() if label.startswith("command ")]
        self.assertGreater(len(labels), 50)

    def test_no_help_file_is_shadowed_by_a_command(self):
        problems = shadowed_entries()
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_entry_keys_are_unique(self):
        for dicts in (HELP_ENTRY_DICTS, NEWS_ENTRY_DICTS):
            keys = [entry["key"].lower() for entry in dicts]
            self.assertEqual(len(keys), len(set(keys)))

    def test_no_markdown_left(self):
        problems = []
        for label, raw in all_entries():
            if label.startswith("command "):
                continue
            for match in MARKDOWN.finditer(raw):
                line = raw.count("\n", 0, match.start()) + 1
                problems.append(f"{label}:{line}: {match.group(0).strip()}")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_checker_catches_bad_references(self):
        """The checks above fail on the mistakes they exist for."""
        self.assertIsNone(resolve_token("+hunt/staffed"))
        self.assertIsNone(resolve_token("job/submit"))
        self.assertIsNotNone(resolve_token("+chargen"))
        self.assertIsNotNone(resolve_token("+roll"))  # the command is `roll`
        self.assertIsNotNone(resolve_token("+hunt/nosuchswitch"))
        self.assertIsNotNone(resolve_token("roll/name"))  # 'name' is a string in CmdRoll, not a switch
        self.assertIsNone(resolve_token("roll/willpower"))
        self.assertIsNotNone(MARKDOWN.search("See [the guide](http://x)"))
        self.assertIsNotNone(MARKDOWN.search("an *italic* word"))
        self.assertNotIn("nosuchtopic", topic_index())


class KnownWrongInstructionTests(SimpleTestCase):
    """Instructions that name a real command, but one the reader can't use."""

    PLAYER_FORBIDDEN = (
        # Builder-only: players file jobs with job/submit.
        re.compile(r"(?<![\w/])\+?job/create\b|\+job/admin/create\b"),
        # Removed in-game chargen.
        re.compile(r"\+chargen\b|\bcharcreate\b"),
    )

    def test_no_player_text_points_at_staff_or_removed_commands(self):
        problems = []
        for entry in [*HELP_ENTRY_DICTS, *NEWS_ENTRY_DICTS]:
            if "perm(" in (entry.get("locks", "") or ""):
                continue  # staff-only entries may name staff commands
            text = strip_ansi(entry["text"])
            for pattern in self.PLAYER_FORBIDDEN:
                for match in pattern.finditer(text):
                    problems.append(f"{entry['key']}: {match.group(0)}")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_no_touchstone_cap_from_humanity(self):
        """Core p.172-173: Touchstones go with Convictions, not Humanity / 2."""
        for label, raw in all_entries():
            text = strip_ansi(raw).lower()
            self.assertNotRegex(text, r"touchstones?[^.\n]*humanity\s*(?:÷|/|//|divided by)\s*2", label)

    def test_staff_approval_entry_is_builder_only(self):
        entries = [e for e in HELP_ENTRY_DICTS if e["key"] == "staff-approval"]
        self.assertEqual(len(entries), 1, "world/help/staff/staff-approval.yaml must load as YAML")
        locks = entries[0].get("locks", "")
        self.assertIn("read:perm(Builder)", locks)
        self.assertIn("view:perm(Builder)", locks)


class PowerListTests(SimpleTestCase):
    def test_disciplines_powers_matches_v5_data(self):
        """help disciplines_powers lists every core power with its level and Rouse cost."""
        from world.v5_data import DISCIPLINES

        text = next(e["text"] for e in HELP_ENTRY_DICTS if e["key"] == "disciplines_powers")
        listed = {
            name.strip().lower(): (int(level), cost.strip())
            for name, level, cost in re.findall(r"^- (.+?) \((\d), ([^;):]+)", text, re.M)
        }
        expected = {}
        for info in DISCIPLINES.values():
            for level, powers in (info.get("powers") or {}).items():
                for power in powers:
                    cost = f"{power['rouse']} Rouse" if power["rouse"] else "free"
                    expected[power["name"].lower()] = (level, cost)
        self.assertEqual(listed, expected)


class PlayerLockTests(EvenniaCommandTest):
    """Commands named in player-readable help and news are ones a player may use."""

    # Deliberate "staff do this with X" mentions in player-facing text.
    STAFF_MENTIONS = {
        "boons-guide": {"+boonadmin", "+statusadmin"},
        "boon_commands": {"+boonadmin", "+statusadmin"},
        "status-guide": {"+statusadmin", "+boonadmin"},
        "status_commands": {"+statusadmin"},
        "social_commands": {"+statusadmin"},
        "xp-guide": {"+xpaward"},
    }

    def test_player_text_names_only_player_commands(self):
        player = self.char2
        player.permissions.remove("Developer")
        self.account2.permissions.remove("Developer")
        problems = []
        for key, token, cmd in player_tokens():
            if cmd.access(player, "cmd"):
                continue
            if cmd.key in self.STAFF_MENTIONS.get(key, set()):
                continue
            problems.append(f"{key}: {token} ({cmd.key} is locked {cmd.locks!r})")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


class CmdsetSurvivalTests(SimpleTestCase):
    def test_every_added_command_survives_the_merge(self):
        """Each class added in default_cmdsets.py is in the built cmdset."""
        for cmdset_name, classes in _added_commands().items():
            cmdset = getattr(default_cmdsets, cmdset_name)()
            cmdset.at_cmdset_creation()
            present = {type(cmd) for cmd in cmdset.commands}
            for cmd_class in classes:
                self.assertIn(cmd_class, present, f"{cmdset_name}: {cmd_class.__name__} was shadowed")

    def test_news_is_readable_before_puppeting(self):
        """New players have no approved character yet; the welcome text sends them to news."""
        account = AccountCmdSet()
        account.at_cmdset_creation()
        self.assertIn("news", account.get_all_cmd_keys_and_aliases())

    def test_game_commands_do_not_shadow_each_other_across_sets(self):
        """A puppeting player has both sets; a game command must not hide another."""
        names = {}
        clashes = []
        for cmdset_class in (CharacterCmdSet, AccountCmdSet, SessionCmdSet):
            cmdset = cmdset_class()
            cmdset.at_cmdset_creation()
            for cmd in cmdset.commands:
                for name in (cmd.key, *cmd.aliases):
                    other = names.setdefault(name.lower(), type(cmd))
                    ours = type(cmd).__module__.startswith(GAME_MODULES)
                    if other is not type(cmd) and (ours or other.__module__.startswith(GAME_MODULES)):
                        clashes.append(f"{name}: {other.__name__} / {type(cmd).__name__}")
        self.assertEqual(clashes, [])


class _HelpNoPager(CmdHelp):
    help_more = False  # no pager, so the whole text comes back


class HelpLookupTests(EvenniaCommandTest):
    """What `help <x>` actually shows in game."""

    def _help(self, query, caller=None):
        cmdset = CharacterCmdSet()
        cmdset.at_cmdset_creation()
        return self.call(_HelpNoPager(), query, cmdset=cmdset, caller=caller or self.char1)

    def test_help_roll_is_the_command(self):
        self.assertIn("Usage:", self._help("roll"))

    def test_help_roll_guide_is_the_guide(self):
        self.assertIn("DICE ROLLING MECHANICS", self._help("roll-guide"))

    def test_help_hunger_guide_is_the_guide(self):
        self.assertIn("HUNGER SYSTEM", self._help("hunger-guide"))

    def test_staff_approval_hidden_from_players(self):
        self.char2.permissions.remove("Developer")
        self.assertNotIn("staff-approval", self._help("", caller=self.char2))
        self.assertNotIn("CHARACTER APPROVAL", self._help("staff-approval", caller=self.char2))

    def test_staff_approval_shown_to_builders(self):
        self.assertIn("staff-approval", self._help(""))
        self.assertIn("CHARACTER APPROVAL", self._help("staff-approval"))
