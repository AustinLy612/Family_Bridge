"""Individual skill learning (Plan §5.5; Phase 5).

- `profile`: adolescent profile questionnaire (step 0) and its tag lists.
- `selection`: selection context (history, recent, below-mastery skills) and the repeat guard.
- `teaching`: the adolescent teaching process (D21 state machine, SSE chat, auto-complete).
- `testing`: skill tests (background generation with retries, mastery at >= 4/5, retakes).
- `caregiver`: caregiver structured lessons (D8/D23).
- `progress`: non-competitive progress and lesson history (Plan §5.13, D57).
"""
