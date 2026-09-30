"""
AI Storyteller Framework for V5 Systems

Provides AI-driven storytelling for hunting sessions, handling complications,
consequences, and interactive narrative responses.

This framework is designed to be extended with actual AI integration (GPT-4, Claude, etc.)
but provides a rule-based system as a fallback.
"""

import random
from .hunting_utils import generate_hunting_opportunity, HUNTING_COMPLICATIONS
from .blood_utils import feed, increase_hunger
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY,
    GOLD, RESET
)


class HuntingSession:
    """
    Represents an active hunting session with AI Storyteller guidance.

    This session tracks the state of a hunt and provides narrative responses
    based on player actions.
    """

    def __init__(self, character, location="street"):
        """
        Initialize hunting session.

        Args:
            character: Character object
            location (str): Hunting location
        """
        self.character = character
        self.location = location
        self.opportunity = generate_hunting_opportunity(location)
        self.state = "spotting"  # spotting, approaching, feeding, aftermath
        self.complications = []
        self.player_actions = []
        self.rolls_made = []

    def process_action(self, action_text):
        """
        Process player's action and return AI Storyteller response.

        Args:
            action_text (str): Player's described action

        Returns:
            dict: Storyteller response
                - narrative: Storyteller's narrative response
                - prompt: What the Storyteller asks for next
                - state: Current session state
                - requires_roll: Whether a roll is needed
                - roll_type: Type of roll needed (if any)
        """
        self.player_actions.append({
            "state": self.state,
            "action": action_text
        })

        # Process based on current state
        if self.state == "spotting":
            return self._process_spotting(action_text)
        elif self.state == "approaching":
            return self._process_approaching(action_text)
        elif self.state == "feeding":
            return self._process_feeding(action_text)
        elif self.state == "aftermath":
            return self._process_aftermath(action_text)

    def _process_spotting(self, action_text):
        """Process actions during spotting phase."""
        # Player has spotted prey, now choosing approach
        self.state = "approaching"

        # Analyze player's action to determine approach
        action_lower = action_text.lower()

        if any(word in action_lower for word in ["sneak", "stalk", "follow", "shadow"]):
            approach = "stealthy"
            skill = "stealth"
            narrative = (
                f"You move silently through the {self.location}, keeping to the shadows as you stalk your prey. "
                f"The {self.opportunity['prey_description']} remains unaware of your presence... for now."
            )
        elif any(word in action_lower for word in ["charm", "seduce", "flirt", "approach", "talk"]):
            approach = "social"
            skill = "persuasion"
            narrative = (
                f"You approach with confidence and charm, catching the eye of your target. "
                f"{self.opportunity['hook']} - this might work to your advantage."
            )
        elif any(word in action_lower for word in ["dominate", "mesmerize", "command", "compel"]):
            approach = "discipline"
            skill = "dominate"
            narrative = (
                f"You lock eyes with your prey, preparing to bend their will to yours. "
                f"Your Beast stirs as you reach for your Disciplines..."
            )
        else:
            # Default to direct approach
            approach = "direct"
            skill = "intimidation"
            narrative = (
                f"You move directly toward your target. "
                f"There's no subtlety here - just predator and prey."
            )

        return {
            "narrative": narrative,
            "prompt": f"Roll |y{skill.title()}|n to see how your approach goes.",
            "state": self.state,
            "requires_roll": True,
            "roll_type": skill,
            "approach": approach
        }

    def _process_approaching(self, action_text):
        """Process actions during approaching phase."""
        # Check if this is a roll result or another action
        # For now, assume successful approach
        self.state = "feeding"

        # Generate potential complication
        complication_chance = random.randint(1, 100)
        has_complication = complication_chance <= 30  # 30% chance

        if has_complication:
            comp = random.choice(HUNTING_COMPLICATIONS)
            self.complications.append(comp)

            if comp["type"] == "witness":
                narrative = (
                    f"You successfully corner your prey, but as you prepare to feed, "
                    f"you notice |r{comp['desc']}|n. You have moments to decide..."
                )
                prompt = "What do you do? (Feed quickly and risk exposure, or abandon this hunt?)"
            elif comp["type"] == "struggle":
                narrative = (
                    f"As you sink your fangs in, |r{comp['desc']}|n! "
                    f"They're fighting back harder than expected."
                )
                prompt = "How do you handle this? (Restrain them, use Dominate, or let them go?)"
            else:
                narrative = (
                    f"Something goes wrong: |r{comp['desc']}|n. "
                    f"The situation is more complex than you anticipated."
                )
                prompt = "How do you respond?"

        else:
            narrative = (
                f"You successfully isolate your prey. The vessel is vulnerable, "
                f"their {self.opportunity['resonance']['type']} resonance palpable in the air."
            )
            prompt = "Do you feed carefully, or give in to your Hunger?"

        return {
            "narrative": narrative,
            "prompt": prompt,
            "state": self.state,
            "requires_roll": False,
            "has_complication": has_complication
        }

    def _process_feeding(self, action_text):
        """Process the actual feeding."""
        self.state = "aftermath"

        action_lower = action_text.lower()

        # Determine feeding style
        if any(word in action_lower for word in ["careful", "gentle", "slow", "controlled"]):
            feeding_style = "careful"
            slake = 1
            risk_masquerade = False
            narrative_flavor = "You feed carefully, taking only what you need."
        elif any(word in action_lower for word in ["hungry", "fast", "quick", "desperate"]):
            feeding_style = "hurried"
            slake = 2
            risk_masquerade = True
            narrative_flavor = "You feed quickly, your Hunger driving you."
        elif any(word in action_lower for word in ["drain", "kill", "everything", "completely"]):
            feeding_style = "lethal"
            slake = 3
            risk_masquerade = True
            narrative_flavor = "You drain them completely. The vessel goes limp in your arms."
        else:
            feeding_style = "normal"
            slake = 2
            risk_masquerade = False
            narrative_flavor = "You feed, the warm blood satisfying your Hunger."

        # Apply feeding
        result = feed(
            self.character,
            vessel_type="human",
            slake=slake,
            resonance_type=self.opportunity['resonance']['type'],
            resonance_intensity=self.opportunity['resonance']['intensity']
        )

        # Build narrative
        narrative = narrative_flavor + "\n"
        narrative += f"The {self.opportunity['resonance']['type']} resonance flows through you.\n"
        narrative += result["message"]

        # Add complications
        if self.complications:
            narrative += f"\n\n|rConsequences:|n"
            for comp in self.complications:
                narrative += f"\n- {comp['desc']}"

        # Determine aftermath
        if feeding_style == "lethal":
            prompt = "The vessel is dead. What do you do with the body?"
        elif risk_masquerade and self.complications:
            prompt = "The hunt was messy. How do you cover your tracks?"
        else:
            prompt = "The hunt is complete. You fade back into the night."

        return {
            "narrative": narrative,
            "prompt": prompt,
            "state": self.state,
            "requires_roll": False,
            "feeding_result": result
        }

    def _process_aftermath(self, action_text):
        """Process aftermath actions."""
        # Hunt is complete
        narrative = "You disappear into the darkness, the taste of blood still on your lips."

        return {
            "narrative": narrative,
            "prompt": None,
            "state": "complete",
            "requires_roll": False,
            "session_complete": True
        }


class AIStorytellerEngine:
    """
    AI Storyteller Engine for managing narrative hunting sessions.

    This is a framework that can be extended with actual AI integration
    (OpenAI GPT-4, Anthropic Claude, etc.) but provides rule-based storytelling
    as a fallback.
    """

    def __init__(self):
        """Initialize AI Storyteller Engine."""
        self.active_sessions = {}  # character_id: HuntingSession

    def start_hunt(self, character, location="street"):
        """
        Start a new hunting session for a character.

        Args:
            character: Character object
            location (str): Hunting location

        Returns:
            dict: Initial scene description
        """
        session = HuntingSession(character, location)
        self.active_sessions[character.id] = session

        return {
            "narrative": self._generate_opening_scene(session),
            "prompt": "How do you approach your prey?",
            "opportunity": session.opportunity
        }

    def process_player_input(self, character, input_text):
        """
        Process player's action/input during a hunt.

        Args:
            character: Character object
            input_text (str): Player's action or description

        Returns:
            dict: Storyteller's response
        """
        session = self.active_sessions.get(character.id)

        if not session:
            return {
                "error": "No active hunting session. Use +hunt/ai to start."
            }

        response = session.process_action(input_text)

        # If session is complete, clean up
        if response.get("session_complete"):
            del self.active_sessions[character.id]

        return response

    def _generate_opening_scene(self, session):
        """Generate opening scene narrative."""
        opp = session.opportunity

        narrative = f"{PALE_IVORY}The {session.location} at night...{RESET}\n\n"
        narrative += f"You prowl through the {session.location}, your Hunger gnawing at you. "
        narrative += f"The city's pulse thrums around you - mortals going about their lives, "
        narrative += f"unaware of the predator in their midst.\n\n"
        narrative += f"Then you spot them: {opp['prey_description']}.\n"
        narrative += f"{opp['hook']}\n\n"
        narrative += f"You sense their {GOLD}{opp['resonance']['type']}{RESET} resonance - "
        narrative += f"{opp['resonance']['intensity_name'].lower()}. "

        if opp['resonance']['intensity'] >= 2:
            narrative += f"Strong enough to enhance your Disciplines. "

        narrative += f"This one could satisfy your Hunger."

        return narrative

    def cancel_hunt(self, character):
        """
        Cancel an active hunting session.

        Args:
            character: Character object

        Returns:
            bool: True if session was canceled
        """
        if character.id in self.active_sessions:
            del self.active_sessions[character.id]
            return True
        return False

    def get_active_session(self, character):
        """
        Get active hunting session for a character.

        Args:
            character: Character object

        Returns:
            HuntingSession or None
        """
        return self.active_sessions.get(character.id)


# Global AI Storyteller instance
_storyteller = None


def get_storyteller():
    """Get the global AI Storyteller instance."""
    global _storyteller
    if _storyteller is None:
        _storyteller = AIStorytellerEngine()
    return _storyteller
