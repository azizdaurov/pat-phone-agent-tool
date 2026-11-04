"""On a call Pat answered, does Haiku ever say it is the one calling? Old prompt against new, real Haiku, text only, no phone.
Usage: incoming_direction_eval.py [runs]"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pat
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
SAYS_IT_CALLED = re.compile(r"\b(i'm|i am|i was|i've|i have|i) (calling|called|rang)\b|\bcalling (to|on behalf|for|because|about)|"
                            r"звоню|позвонил|звонил|набрал|по поручению", re.I)
# Modelled on the answered calls where it went wrong: the caller names themselves, asks for Aziz, or says little.
CASES = [
    ("en", ["Hi, this is Justin."]),
    ("en", ["Hello, I wanted to ask Aziz about Friday."]),
    ("en", ["Hello?", "Who is this?"]),
    ("ru", ["Алло, это Рустам."]),
    ("ru", ["Здравствуйте, мне нужен Азиз, по поводу пятницы."]),
]


def replies(language, lines, incoming):
    brief = CallBrief.from_dict({"goal": pat.DEFAULT_ANSWER_GOAL, "language": language})
    brief.incoming = incoming
    opening = pat.OPENINGS["answer"][language].format(owner="Aziz", owner_ru="Азиз")
    brain = pat.Brain(language, system_prompt=brief.haiku_prompt(pat.SYSTEM_PROMPTS[language], opening, "Aziz", "abc123"))
    said = ["".join(brain.ask(line)).replace(pat.END_MARK, "").strip() for line in lines]
    brain.close()
    return said


REPEATS_OPENING = re.compile(r"might hear this conversation|может слышать этот разговор", re.I)
repeated = {False: 0, True: 0}
score = {False: [0, 0], True: [0, 0]}
for language, lines in CASES:
    for incoming in (False, True):
        print(f"=== {'new prompt' if incoming else 'old prompt'}: {lines[0]}", flush=True)
        for _ in range(RUNS):
            said = replies(language, lines, incoming)
            wrong = any(SAYS_IT_CALLED.search(reply) for reply in said)
            again = any(REPEATS_OPENING.search(reply) for reply in said)
            score[incoming][0] += wrong
            score[incoming][1] += 1
            repeated[incoming] += again
            print(f"   {'CALLED' if wrong else 'ok    '}{' REPEATED' if again else ''} " + " | ".join(said), flush=True)
for incoming, (wrong, total) in score.items():
    print(f"{'new' if incoming else 'old'} prompt: said it was calling in {wrong} of {total} calls, "
          f"repeated the whole opening in {repeated[incoming]}", flush=True)
