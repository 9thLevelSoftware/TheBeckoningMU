"""
Roll Result Parser and Interpreter for V5 Dice System

This module provides the RollResult class which comprehensively analyzes
dice roll outcomes according to Vampire: The Masquerade 5th Edition rules.
"""

from typing import List
from evennia.utils.ansi import ANSIString


class RollResult:
    """
    The outcome of one V5 roll, analysed by the core rules (QR p.4).

    - Each die showing 6-10 is one success.
    - Each pair of 10s adds two more, so a pair is worth four successes in
      total: one 10 is 1 success, two are 4, three are 5, four are 8.
    - The roll succeeds when successes >= difficulty. At difficulty 0 it
      still needs at least one success.
    - A critical is a successful roll with at least one pair of 10s.
    - A messy critical is a critical with a 10 on a Hunger die.
    - A bestial failure is a failed roll with a 1 on any Hunger die.

    Attributes:
        regular_dice (list[int]): Regular dice results (1-10)
        hunger_dice (list[int]): Hunger dice results (1-10)
        all_dice (list[int]): Combined regular and hunger dice
        difficulty (int): Target number of successes needed
        total_successes (int): Total successes rolled
        is_success (bool): Whether difficulty was met
        margin (int): Difference between successes and difficulty
        is_critical (bool): Successful roll with a pair of 10s
        is_messy_critical (bool): Critical with a Hunger 10
        is_bestial_failure (bool): Failed roll with a Hunger 1
        result_type (str): Overall result classification
    """

    def __init__(self, regular_dice: List[int], hunger_dice: List[int], difficulty: int = 0):
        """
        Initialize roll result and perform all analysis.

        Args:
            regular_dice: Regular dice results (1-10)
            hunger_dice: Hunger dice results (1-10)
            difficulty: Target successes needed (0 means any success wins)
        """
        self.regular_dice = list(regular_dice)
        self.hunger_dice = list(hunger_dice)
        self.all_dice = self.regular_dice + self.hunger_dice
        self.difficulty = difficulty

        self.tens = sum(1 for die in self.all_dice if die == 10)
        self.total_successes = self._count_successes()
        if difficulty > 0:
            self.is_success = self.total_successes >= difficulty
        else:
            self.is_success = self.total_successes > 0
        self.margin = self.total_successes - difficulty

        self.is_critical = self.is_success and self.tens >= 2
        self.is_messy_critical = self.is_critical and 10 in self.hunger_dice
        self.is_bestial_failure = not self.is_success and 1 in self.hunger_dice

        self.result_type = self._interpret_result()

    def _count_successes(self) -> int:
        """Each 6-10 is one success; each pair of 10s adds two more."""
        singles = sum(1 for die in self.all_dice if die >= 6)
        return singles + 2 * (self.tens // 2)

    def _interpret_result(self) -> str:
        """
        Interpret overall result type for display and game logic.

        Result types:
        - 'bestial_failure': Failed with a Hunger 1
        - 'failure': Failed without bestial complications
        - 'messy_critical': Critical success with Hunger complications
        - 'critical_success': Critical success without complications
        - 'success': Normal success

        Returns:
            String describing result type
        """
        if not self.is_success:
            return 'bestial_failure' if self.is_bestial_failure else 'failure'
        elif self.is_messy_critical:
            return 'messy_critical'
        elif self.is_critical:
            return 'critical_success'
        else:
            return 'success'

    def format_result(self, show_details: bool = True) -> str:
        """
        Format result for display with ANSI colors.

        Uses color coding:
        - Regular dice: White
        - Hunger dice: Red
        - Successes (6-9): Green
        - Criticals (10): Bright Yellow
        - Failures (1-5): Dark Gray

        Args:
            show_details: If True, show detailed breakdown

        Returns:
            Formatted string with ANSI color codes
        """
        output = []

        # Format dice display
        if show_details:
            if self.regular_dice:
                regular_str = self._format_dice_list(self.regular_dice, is_hunger=False)
                output.append(f"|wRegular:|n {regular_str}")

            if self.hunger_dice:
                hunger_str = self._format_dice_list(self.hunger_dice, is_hunger=True)
                output.append(f"|rHunger:|n {hunger_str}")

            output.append("")  # Blank line

        # Format success count
        success_color = '|g' if self.is_success else '|r'
        output.append(f"{success_color}Successes: {self.total_successes}|n", )

        if self.difficulty > 0:
            output.append(f"Difficulty: {self.difficulty} (margin: {self.margin:+d})")

        # Format result type with appropriate messaging
        result_msg = self._get_result_message()
        output.append(f"\n{result_msg}")

        return "\n".join(output)

    def _format_dice_list(self, dice: List[int], is_hunger: bool = False) -> str:
        """
        Format a list of dice with appropriate color coding.

        Args:
            dice: List of die values (1-10)
            is_hunger: Whether these are Hunger dice (affects color)

        Returns:
            Formatted string with colored dice
        """
        formatted = []
        for die in dice:
            if die == 10:
                # Criticals in bright yellow
                formatted.append(f"|y|h{die}|n")
            elif die >= 6:
                # Successes in green
                formatted.append(f"|g{die}|n")
            elif die == 1 and is_hunger:
                # Hunger 1s in bright red (potential bestial failure)
                formatted.append(f"|r|h{die}|n")
            else:
                # Failures in dark gray
                formatted.append(f"|x{die}|n")

        return f"[{', '.join(formatted)}]"

    def _get_result_message(self) -> str:
        """
        Get narrative result message based on result type.

        Returns:
            Formatted message describing the result
        """
        if self.result_type == 'bestial_failure':
            return ("|r|h** BESTIAL FAILURE **|n\n"
                   "You fail, and a Hunger die shows a 1: the Beast takes its due.\n"
                   "Act out a Compulsion; the Storyteller decides the details.")

        elif self.result_type == 'failure':
            return "|rFailure|n\nYou do not achieve your goal."

        elif self.result_type == 'messy_critical':
            return ("|y|h** MESSY CRITICAL **|n\n"
                   f"You succeed with |g{self.total_successes}|n successes, but a Hunger die shows a 10.\n"
                   "Messy critical: the Storyteller decides the complication.")

        elif self.result_type == 'critical_success':
            return ("|y|h** CRITICAL SUCCESS **|n\n"
                   f"You achieve a dramatic success with |g{self.total_successes}|n successes!\n"
                   "The Storyteller may grant additional benefits.")

        else:  # 'success'
            margin_text = f" (margin: {self.margin:+d})" if self.difficulty > 0 else ""
            return f"|gSuccess!|n You achieve your goal with |g{self.total_successes}|n successes{margin_text}."

    def __str__(self) -> str:
        """String representation for logging/debugging."""
        return f"RollResult(successes={self.total_successes}, type={self.result_type})"

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return (f"RollResult(regular={self.regular_dice}, hunger={self.hunger_dice}, "
                f"difficulty={self.difficulty}, successes={self.total_successes}, "
                f"type={self.result_type})")
