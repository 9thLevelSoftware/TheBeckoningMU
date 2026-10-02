"""
Roll Result Parser and Interpreter for V5 Dice System

This module provides the RollResult class which comprehensively analyzes
dice roll outcomes according to Vampire: The Masquerade 5th Edition rules.
"""

from typing import List
from evennia.utils.ansi import ANSIString


class RollResult:
    """
    Comprehensive V5 roll result with all analysis.

    Analyzes dice rolls to determine:
    - Total successes (6-9 = 1 success, 10 = 2 successes)
    - Success vs failure (compared to difficulty)
    - Critical wins (pair of 10s)
    - Messy Criticals (critical with Hunger die showing 10)
    - Bestial Failures (failure with only Hunger dice showing 1s)

    Attributes:
        regular_dice (list[int]): Regular dice results (1-10)
        hunger_dice (list[int]): Hunger dice results (1-10)
        all_dice (list[int]): Combined regular and hunger dice
        difficulty (int): Target number of successes needed
        total_successes (int): Total successes rolled
        is_success (bool): Whether difficulty was met
        margin (int): Difference between successes and difficulty
        is_critical (bool): Whether a pair of 10s was rolled
        is_messy_critical (bool): Whether critical included Hunger die
        is_bestial_failure (bool): Whether failure had only Hunger 1s
        result_type (str): Overall result classification
    """

    def __init__(self, regular_dice: List[int], hunger_dice: List[int], difficulty: int = 0):
        """
        Initialize roll result and perform all analysis.

        Args:
            regular_dice: Regular dice results (1-10)
            hunger_dice: Hunger dice results (1-10)
            difficulty: Target successes needed (0+ means any success wins)
        """
        self.regular_dice = regular_dice
        self.hunger_dice = hunger_dice
        self.all_dice = regular_dice + hunger_dice
        self.difficulty = difficulty

        # Analyze outcomes in one pass over the two dice groups.
        (
            self.total_successes,
            self.is_success,
            self.is_critical,
            self.is_messy_critical,
            self.is_bestial_failure,
        ) = self._analyze_dice()
        self.margin = self.total_successes - difficulty

        # Result interpretation
        self.result_type = self._interpret_result()
    def _analyze_dice(self) -> tuple[int, bool, bool, bool, bool]:
        """Compute successes and V5 special-result flags in one pass."""
        successes = 0
        tens = 0
        hunger_tens = 0
        regular_ones = 0
        hunger_ones = 0

        for die in self.regular_dice:
            if die >= 6:
                successes += 2 if die == 10 else 1
            if die == 10:
                tens += 1
            elif die == 1:
                regular_ones += 1

        for die in self.hunger_dice:
            if die >= 6:
                successes += 2 if die == 10 else 1
            if die == 10:
                tens += 1
                hunger_tens += 1
            elif die == 1:
                hunger_ones += 1

        is_success = successes >= self.difficulty if self.difficulty > 0 else successes > 0
        is_critical = tens >= 2
        is_messy_critical = is_critical and hunger_tens >= 1
        is_bestial_failure = not is_success and hunger_ones > 0 and regular_ones == 0
        return successes, is_success, is_critical, is_messy_critical, is_bestial_failure

    def _count_successes(self) -> int:
        """Count total successes according to V5 rules."""
        return self._analyze_dice()[0]

    def _check_critical(self) -> bool:
        """Check whether at least two dice show 10."""
        return self._analyze_dice()[2]

    def _check_messy_critical(self) -> bool:
        """Check whether a critical includes a Hunger 10."""
        return self._analyze_dice()[3]

    def _check_bestial_failure(self) -> bool:
        """Check whether the failed roll has only Hunger dice showing 1."""
        return self._analyze_dice()[4]

    def _interpret_result(self) -> str:
        """
        Interpret overall result type for display and game logic.

        Result types:
        - 'bestial_failure': Failed with only Hunger 1s (Beast takes over)
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
                   "You fail catastrophically as the Beast seizes control!\n"
                   "The Storyteller will introduce a complication related to your vampiric nature.")

        elif self.result_type == 'failure':
            return "|rFailure|n\nYou do not achieve your goal."

        elif self.result_type == 'messy_critical':
            return ("|y|h** MESSY CRITICAL **|n\n"
                   f"You succeed spectacularly with |g{self.total_successes}|n successes,\n"
                   "but your Beast influences the outcome. The Storyteller will\n"
                   "introduce a complication related to your vampiric Hunger.")

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
