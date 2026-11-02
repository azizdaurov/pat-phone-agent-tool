"""The framed summary an agent shows in chat when a call is over. Plain text, so it works in any code block."""
import re
import unicodedata

TEXT_WIDTH = 46
MAX_LABEL_WIDTH = 13
OUTCOMES = {"done": "Done", "partial": "Partly done", "failed": "Not done"}
STATUSES = {"done": "Finished, no report", "no_answer": "No answer", "failed": "Failed", "crashed": "Failed"}


def display_width(text):
    """Columns text takes in a monospaced font; plain len() would misalign the frame for wide characters."""
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in text)


def _clean(value):
    # One line, and nothing that could end the code block the card is shown in.
    return re.sub(r"\s+", " ", str(value).replace("`", "'")).strip()


def _wrap(text, limit):
    lines = []
    current = ""
    for word in text.split():
        while display_width(word) > limit:  # a word too long for the frame, such as a web address
            cut = len(word)
            while display_width(word[:cut]) > limit:
                cut -= 1
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut])
            word = word[cut:]
        joined = f"{current} {word}" if current else word
        if display_width(joined) > limit:
            lines.append(current)
            current = word
        else:
            current = joined
    if current:
        lines.append(current)
    return lines or [""]


def _duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def _answer_rows(answers):
    rows = []
    for item in answers:
        if not isinstance(item, dict):
            continue
        label = _clean(item.get("label") or item.get("need") or "Answer")
        value = item.get("answer")
        if value in (None, ""):
            value = "not obtained"
        else:
            value = _clean(value) + ("" if item.get("confirmed") else " (not confirmed)")
        rows.append((label, value))
    labels = _wrap_labels(rows)
    column = max((display_width(label) for label in labels), default=0) + 2
    lines = []
    for (_, value), label in zip(rows, labels):
        for index, part in enumerate(_wrap(value, TEXT_WIDTH - column)):
            start = label if index == 0 else ""
            lines.append(start + " " * (column - display_width(start)) + part)
    return lines


def _wrap_labels(rows):
    """Long labels are shortened, so answers stay in one tidy column."""
    labels = []
    for label, _ in rows:
        if display_width(label) > MAX_LABEL_WIDTH:
            label = _wrap(label, MAX_LABEL_WIDTH - 1)[0].rstrip(",;:") + "…"
        labels.append(label)
    return labels


def _bullets(items):
    lines = []
    for item in items:
        for index, part in enumerate(_wrap(_clean(item), TEXT_WIDTH - 2)):
            lines.append(("• " if index == 0 else "  ") + part)
    return lines


def _reached_line(state):
    """Whether the call found who it was looking for. Comes from code, not from the model's report."""
    target = _clean(state.get("target") or "")
    return {"confirmed": f"Reached {target}".strip(),
            "not_available": f"Not available: {target}".strip(": "),
            "wrong_number": f"Wrong number, not {target}" if target else "Wrong number",
            "unclear": f"Couldn't confirm it was {target}" if target else "Couldn't confirm who answered",
            }.get(state.get("reached"))


def render_card(state):
    """state is what read_call has: status, reason, report, number, seconds. Any of them may be missing."""
    report = state.get("report") if isinstance(state.get("report"), dict) else {}
    outcome = OUTCOMES.get(report.get("outcome")) or STATUSES.get(state.get("status"), "Over")
    facts = [outcome]
    if state.get("number"):
        facts.append(_clean(state["number"]))
    if state.get("seconds") is not None:
        facts.append(_duration(state["seconds"]))

    sections = [_wrap("  ·  ".join(facts), TEXT_WIDTH)]
    reached = _reached_line(state)
    if reached:
        sections[0] += _wrap(reached, TEXT_WIDTH)
    answers = _answer_rows(report.get("answers") or [])
    if answers:
        sections.append(answers)
    important = [item for item in report.get("important_details") or [] if _clean(item)]
    if important:
        sections.append(["IMPORTANT"] + _bullets(important))
    if report.get("summary"):
        sections.append(_wrap(_clean(report["summary"]), TEXT_WIDTH))
    if report.get("follow_up") and _clean(report["follow_up"]):
        sections.append(["NEXT"] + _wrap(_clean(report["follow_up"]), TEXT_WIDTH))
    if not report and state.get("reason"):
        sections.append(_wrap(_clean(state["reason"]), TEXT_WIDTH))

    inner = TEXT_WIDTH + 4
    title = " Call Summary "
    left = (inner - len(title)) // 2
    card = ["╭" + "─" * left + title + "─" * (inner - left - len(title)) + "╮"]
    for index, section in enumerate(sections):
        if index:
            card.append("├" + "─" * inner + "┤")
        for line in section:
            card.append("│  " + line + " " * (TEXT_WIDTH - display_width(line)) + "  │")
    card.append("╰" + "─" * inner + "╯")
    return "\n".join(card)
