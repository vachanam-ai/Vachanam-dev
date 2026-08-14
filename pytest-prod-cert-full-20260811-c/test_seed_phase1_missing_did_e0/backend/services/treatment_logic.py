"""Pure logic for treatment-note state. No DB, fully unit-testable."""
from __future__ import annotations


def resolve_is_final(is_final_flag: bool | None, next_steps: str | None) -> bool:
    """Treatment is complete if the 'Mark complete' button sent it, OR the doctor
    typed exactly 'end' as the next step (case-insensitive, whitespace-trimmed).
    A partial match like 'ending soon' or 'send' must NOT close it."""
    if is_final_flag:
        return True
    return (next_steps or "").strip().lower() == "end"
