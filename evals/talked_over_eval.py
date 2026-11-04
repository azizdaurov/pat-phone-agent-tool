"""Someone keeps saying yes and talks over Claude's question. Does that yes get taken as their answer? Replays the call of 3-11-2026
against real Claude: Haiku's next line, the live note's bullet and Sonnet's report. Text only, no phone.
A bare yes over a question they heard none of no longer reaches Haiku at all (see test_supervision.py), so here that case only shows what the words alone do.
Usage: talked_over_eval.py [runs] [--old]   --old uses the wording from before the fix, for Haiku's lines only"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cicero
from call_brief import CONFIRMED_MARK, END_MARK, CallBrief
from live_notes import NOTES_PROMPT, LiveNotes, parse_notes
from observer import OBSERVER_MODEL, Observer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
OLD = "--old" in sys.argv
NONCE = "abc123"
BRIEFS = {
    "ru": {"goal": "Попросить Алекса забрать еду и узнать, заберёт ли он.", "need_from_them": ["Вы заберёте еду?"], "may_share": ["Азиз просит Алекса забрать еду"],
           "done_when": "Алекс сказал, заберёт ли он еду.", "language": "ru", "name": "Алекс", "confidence": "confirmed"},
    "en": {"goal": "Ask Alex to pick up the food and find out whether he will.", "need_from_them": ["Will you pick up the food?"], "may_share": ["Aziz asks Alex to pick up the food"],
           "done_when": "Alex has said whether he will pick up the food.", "language": "en", "name": "Alex", "confidence": "confirmed"},
}
ASKS_AGAIN = r"забер|забрать|сможете|pick up|pick it up|get the food"
SHOULD_ASK = "should ask again"
SHOULD_ACCEPT = "should take it as the answer"


def supervisor(note):
    return f"[SUPERVISOR-{NONCE}] {note}"


def cut_note(heard):
    if not OLD:
        return cicero.cut_message(heard)
    said = f'They heard only: "{heard}".' if heard else "They heard none of it."
    return f"You were cut off during your last reply. {said} Say the rest again only if it still matters."


def start(language):
    brief = CallBrief.from_dict(BRIEFS[language])
    opening = cicero.OPENINGS["dial"][language].format(owner="Aziz", owner_ru="Азиза")
    return brief, cicero.Brain(language, system_prompt=brief.haiku_prompt(cicero.SYSTEM_PROMPTS[language], opening, "Aziz", NONCE))


def say(brain, message):
    return "".join(brain.ask(message)).strip()


def after_task(language, confirm):
    """Up to the moment Haiku has just asked its question. Returns the brain and what it asked."""
    brief, brain = start(language)
    say(brain, confirm)
    return brain, say(brain, supervisor(brief.task_message("Aziz")))


def first_words(text):
    return " ".join(text.split()[:3])


def haiku_cases(language):
    yes, full = ("да", "Да, заберу еду.") if language == "ru" else ("yes", "Yes, I'll pick up the food.")
    confirm = "да да да" if language == "ru" else "yes yes yes"
    return [
        (f"yes over the question, heard none of it ({language})", SHOULD_ASK, confirm, lambda reply: cut_note(""), yes),
        (f"yes over the question, heard only its first 3 words ({language})", SHOULD_ASK, confirm, lambda reply: cut_note(first_words(reply)), yes),
        (f"control: a full answer over the question ({language})", SHOULD_ACCEPT, confirm, lambda reply: cut_note(""), full),
        (f"control: yes after hearing it all ({language})", SHOULD_ACCEPT, confirm, lambda reply: "", yes),
    ]


score = {SHOULD_ASK: [0, 0], SHOULD_ACCEPT: [0, 0]}
for language in ("ru", "en"):
    for name, kind, confirm, note, answer in haiku_cases(language):
        print(f"=== {name}: {kind}", flush=True)
        for run in range(RUNS):
            brain, asked = after_task(language, confirm)
            message = note(asked)
            reply = say(brain, f"{supervisor(message)}\n{answer}" if message else answer)
            brain.close()
            ended = END_MARK in reply
            asks = bool(re.search(ASKS_AGAIN, reply.lower())) and "?" in reply
            passed = (asks and not ended) if kind == SHOULD_ASK else (not asks)
            score[kind][0] += passed
            score[kind][1] += 1
            print(f"   {'ok ' if passed else 'NO '} asked: {asked} | {answer} -> {reply}", flush=True)
for kind, (passed, total) in score.items():
    print(f"Haiku, {kind}: {passed} of {total}", flush=True)

# A yes while the opening is still playing, before its question has reached them. Haiku needs no help with this one: 20 of 20 with no note at all.
opening_score = [0, 0]
for language, words, should_confirm in (("ru", "да", False), ("en", "yes", False), ("ru", "Да, это Алекс.", True), ("en", "Yes, this is Alex.", True)):
    print(f"=== over the opening, {language}: '{words}': {'confirms' if should_confirm else 'should ask again'}", flush=True)
    for run in range(RUNS):
        brief, brain = start(language)
        reply = say(brain, words)
        brain.close()
        passed = (CONFIRMED_MARK in reply) == should_confirm
        opening_score[0] += passed
        opening_score[1] += 1
        print(f"   {'ok ' if passed else 'NO '} {reply}", flush=True)
print(f"Haiku, over the opening: {opening_score[0]} of {opening_score[1]}", flush=True)

# The real call's transcript, and the same call with the question asked again.
HEARD_NOTHING = [("Claude", "Скажите, пожалуйста, это Алекс?"), ("Them", "да да да"), ("Status", "person confirmed; the task starts now"),
                 ("Claude", "Азиз просит вас забрать еду."), ("Claude", "Вы сможете это сделать?"), ("Claude", "(cut off, heard nothing of this reply)"),
                 ("Them", "да"), ("Claude", "Спасибо, Алекс."), ("Claude", "Все готово.")]
ASKED_AGAIN = HEARD_NOTHING[:7] + [("Claude", "Азиз просит вас забрать еду. Вы сможете это сделать?"), ("Them", "да"), ("Claude", "Спасибо, Алекс. До свидания.")]
BRIEF = CallBrief.from_dict(BRIEFS["en"])
report_score = [0, 0]
for name, lines, should_be_yes in (("the real call: never heard the question", HEARD_NOTHING, False), ("control: asked again, then yes", ASKED_AGAIN, True)):
    print(f"=== report, {name}", flush=True)
    for run in range(RUNS):
        sonnet = cicero.Brain("en", system_prompt=BRIEF.observer_prompt("Aziz"), model=OBSERVER_MODEL)
        report = Observer(lambda text: "".join(sonnet.ask(text)), lines, "Aziz").final_report("goodbye", seconds=90)
        sonnet.close()
        answer = ((report or {}).get("answers") or [{}])[0].get("answer")
        is_yes = bool(answer) and bool(re.match(r"\s*(yes|да|will)", str(answer).lower()))
        passed = is_yes == should_be_yes
        report_score[0] += passed
        report_score[1] += 1
        print(f"   {'ok ' if passed else 'NO '} {json.dumps(report, ensure_ascii=False)[:300]}", flush=True)
print(f"Sonnet report: {report_score[0]} of {report_score[1]}", flush=True)

notes_score = [0, 0]
for name, lines, should_have in (("the real call", HEARD_NOTHING[:7], False), ("control: asked again, then yes", ASKED_AGAIN[:9], True)):
    print(f"=== live note, {name}", flush=True)
    for run in range(RUNS):
        brain = cicero.Brain("en", system_prompt=NOTES_PROMPT)
        notes = LiveNotes(lambda text: "".join(brain.ask(text)), BRIEF.need_from_them)
        parsed = parse_notes(notes.ask(notes._prompt(lines)))
        notes.close()
        brain.close()
        value = parsed[0][0]["value"] if parsed and parsed[0] else None
        passed = bool(value) == should_have
        notes_score[0] += passed
        notes_score[1] += 1
        print(f"   {'ok ' if passed else 'NO '} {value}", flush=True)
print(f"Live note: {notes_score[0]} of {notes_score[1]}", flush=True)
