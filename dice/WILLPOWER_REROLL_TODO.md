# Willpower Reroll Implementation Plan

## Current Status

The dice system currently **offers** Willpower rerolls via the `/willpower` switch on `roll` and `power` commands, but does not implement the actual reroll mechanics. When a roll fails, the system displays:

```
You may spend 1 Willpower to reroll up to 3 failed dice.
(Use 'willpower reroll' to attempt reroll)
```

However, the `willpower reroll` command does not exist yet.

## Implementation Requirements

### 1. State Management

Need to store the last roll result for potential reroll:
- Store in `character.ndb.last_roll` (non-persistent, session-only)
- Include: `RollResult` object, roll type, timestamp
- Clear after successful reroll or timeout (30 seconds)

### 2. Willpower Tracking

Need to integrate with character Willpower system:
- Check `character.db.willpower_current` exists
- Ensure character has at least 1 Willpower point
- Deduct 1 Willpower on successful reroll
- Return error if no Willpower available

### 3. CmdWillpowerReroll Command

Create new command:

```python
class CmdWillpowerReroll(Command):
    """
    Reroll failed dice using Willpower.

    Usage:
      willpower reroll

    Costs 1 Willpower point. Can only be used immediately after
    a failed roll that was initiated with the /willpower switch.

    Rerolls up to 3 failed regular dice (showing 1-5).
    Cannot reroll Hunger dice.
    """

    key = "willpower"
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        # Validate 'reroll' argument
        if self.args.strip().lower() != 'reroll':
            self.caller.msg("Usage: willpower reroll")
            return

        # Check for stored roll state
        last_roll = self.caller.ndb.last_roll
        if not last_roll:
            self.caller.msg("|rNo recent roll to reroll.|n")
            return

        # Check roll was eligible (failed, had /willpower switch)
        if not last_roll.get('can_reroll'):
            self.caller.msg("|rThat roll is not eligible for Willpower reroll.|n")
            return

        # Check Willpower availability
        willpower = self.caller.db.willpower_current or 0
        if willpower < 1:
            self.caller.msg("|rYou have no Willpower remaining.|n")
            return

        # Perform reroll
        result = last_roll['result']
        new_result, rerolled_indices = dice_roller.apply_willpower_reroll(result, num_rerolls=3)

        # Deduct Willpower
        self.caller.db.willpower_current -= 1

        # Clear stored roll (can only reroll once)
        self.caller.ndb.last_roll = None

        # Format and display result
        message = self._format_reroll_message(
            old_result=result,
            new_result=new_result,
            rerolled_indices=rerolled_indices,
            willpower_remaining=willpower - 1
        )

        self.caller.location.msg_contents(
            f"|c{self.caller.name}|n spends Willpower to reroll...\n{message}",
            exclude=[self.caller]
        )
        self.caller.msg(message)
```

### 4. Integration with Existing Commands

Modify `CmdRoll.func()` and `CmdRollPower.func()`:

```python
# After rolling, if /willpower switch was used:
if 'willpower' in self.switches and not result.is_success:
    # Store roll state for potential reroll
    self.caller.ndb.last_roll = {
        'result': result,
        'can_reroll': True,
        'timestamp': time.time(),
        'roll_type': 'basic'  # or 'power'
    }
```

### 5. Timeout Cleanup

Add a cleanup function to clear stale roll states:

```python
def clear_stale_rolls():
    """Clear roll states older than 30 seconds."""
    # Could be called at the start of each command
    # Or via a periodic task
    if self.caller.ndb.last_roll:
        timestamp = self.caller.ndb.last_roll.get('timestamp', 0)
        if time.time() - timestamp > 30:
            self.caller.ndb.last_roll = None
```

## Testing Requirements

1. **Basic Reroll**: Test rerolling 3 failed dice
2. **No Willpower**: Test error when Willpower = 0
3. **No Recent Roll**: Test error when no roll to reroll
4. **Timeout**: Test that stale rolls are cleared
5. **Only Once**: Test that same roll can't be rerolled twice
6. **Hunger Dice Exclusion**: Verify Hunger dice are never rerolled

## Files to Modify

1. **`dice/commands.py`**:
   - Add `CmdWillpowerReroll` class
   - Modify `CmdRoll.func()` to store roll state
   - Modify `CmdRollPower.func()` to store roll state

2. **`dice/cmdset.py`**:
   - Add `CmdWillpowerReroll` to `DiceCmdSet`

3. **`dice/tests.py`**:
   - Add `WillpowerRerollTestCase` with tests for all scenarios

## Estimated Complexity

- **Effort**: ~2-3 hours implementation + testing
- **Risk**: Low (isolated feature, doesn't affect existing functionality)
- **Dependencies**: Requires Willpower trait implementation in character system

## Alternative: Simplified Implementation

For a simpler implementation without state management:

```python
# Instead of storing state, just show the command syntax:
message += "\n\n|yYou may immediately use:|n willpower reroll <pool> <hunger>"
message += "\n|x(This will cost 1 Willpower and reroll up to 3 failed dice)|n"

# Then implement willpower reroll as a fresh roll:
class CmdWillpowerReroll(Command):
    def func(self):
        # Parse same args as CmdRoll
        # Deduct Willpower
        # Roll normally
        # No "reroll" logic, just a new roll that costs Willpower
```

This is simpler but less accurate to V5 rules (should improve existing roll, not make new roll).

## Recommendation

**Defer to Phase 6** or later. The core dice system is complete and functional. Willpower rerolls are an advanced feature that can be added after:
1. Willpower system is fully implemented
2. Character sheet tracks current/max Willpower
3. Other Willpower-spending features are designed

For now, the `/willpower` switch serves as a reminder that rerolls are possible in V5, and the implementation can be added in a future sprint.
