"""Pure string-clock helpers matching the existing HH:MM:SS comparison semantics."""


def at_or_after(time_text: str, boundary: str) -> bool:
    return time_text >= boundary


def in_window(time_text: str, start_inclusive: str, end_exclusive: str) -> bool:
    return start_inclusive <= time_text < end_exclusive