"""Sonnet reading the call. It never delays speech: reviews run beside the call, and code keeps interventions rare."""
import json
import re
import threading

from call_brief import CONSULT_REQUEST, REPORT_REQUEST
from real_dates import WRITE_REAL_DATES, date_lines, real_dates

OBSERVER_MODEL = "claude-sonnet-5-5"
REVIEW_EVERY_TURNS = 3  # reads the transcript after every third reply from Haiku
MAX_INTERVENTIONS = 3  # after these, reviews stop too, so a bad call can't become a stream of "one moment"
MIN_TURNS_BETWEEN = 3
NONE = {"action": "none", "note": "", "reason": ""}


def parse_advice(reply):
    """Sonnet's JSON line as a dict. Anything unusable means leave the call alone."""
    data = _first_json(reply)
    if not data or data.get("action") not in ("steer", "correct") or not str(data.get("note", "")).strip():
        return dict(NONE)
    return {"action": data["action"], "note": str(data["note"]).strip(), "reason": str(data.get("reason", ""))}


def _first_json(reply):
    match = re.search(r"\{.*\}", reply or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class Observer:
    """ask sends one message to a kept-open Sonnet, so each review sends only the lines it hasn't seen."""

    def __init__(self, ask, spoken, owner=None, interrupt=None, log=None):
        self.ask = ask
        self.spoken = spoken
        from user_profile import UserProfile
        self.owner = owner or UserProfile().name or "the owner"
        self.lock = threading.Lock()
        self.sent = 0
        self.interventions = 0
        self.reviews = 0
        self.last_turn = None
        self.caller_id = None  # on a call Pat answered: (name Haiku greeted them by, contact label); either may be empty
        self.interrupt = interrupt  # stops the reply Sonnet is writing, keeping its conversation
        self.log = log or (lambda text: print(text, flush=True))
        self.late = None  # a question Sonnet didn't answer in time: {"question", "sent_before", "thread"}
        self.stops = 0  # late answers stopped because a review was due

    def _new_lines(self):
        lines = self.spoken[self.sent:]
        self.sent += len(lines)
        return "\n".join(f"{who}: {text}" for who, text in lines)

    def _take_lock(self, wait):
        """The lock, or False. A late answer to a question no longer counts, so it is stopped instead of waited for."""
        if self.lock.acquire(blocking=False):
            return True
        late = self.late
        if late and late["thread"].is_alive() and self.interrupt:
            try:
                self.interrupt()
            except Exception as error:
                self.log(f"Sonnet couldn't be stopped: {error}")
                return self.lock.acquire(timeout=wait) if wait else False
            if not self.lock.acquire(timeout=5):
                return False
            self.sent = late["sent_before"]  # it never answered those lines, so they are sent again
            late["stopped"] = True
            self.stops += 1
            if self.stops > 1:
                self.log(f"Sonnet stopped again: a late answer was still running when the next check came ({self.stops} times this call)")
            return True
        return self.lock.acquire(timeout=wait) if wait else False

    def _late_note(self):
        """Tells Sonnet, once, that its answer to Haiku's question was never used, so it doesn't think Haiku said it."""
        late, self.late = self.late, None
        if not late:
            return ""
        how = "You were stopped before you finished" if late.get("stopped") else "Your answer came too late"
        return (f'{how} answering Haiku\'s question "{late["question"]}", so it was never used: Haiku told them it can\'t '
                f"decide this and will pass it on to {self.owner}. The lines below follow on from that.\n\n")

    def due(self, turn):
        """Whether to read the transcript after this caller turn."""
        if self.interventions >= MAX_INTERVENTIONS or turn % REVIEW_EVERY_TURNS:
            return False
        return self.last_turn is None or turn - self.last_turn >= MIN_TURNS_BETWEEN

    def review(self, turn):
        """Returns advice. A failure here must not touch the call, so it counts as no advice."""
        if not self._take_lock(wait=0):
            return dict(NONE)  # still busy with an earlier review
        try:
            self.reviews += 1
            note = self._late_note()
            advice = parse_advice(self.ask(note + self._new_lines()))
        except Exception:
            return dict(NONE)
        finally:
            self.lock.release()
        if advice["action"] != "none":
            self.interventions += 1
            self.last_turn = turn
        return advice

    def consult(self, question, seconds=10):
        """Haiku's question, with a time limit because the person is waiting. Returns a note, or None."""
        answer = []
        sent_before = []
        gave_up = threading.Event()

        def run():
            with self.lock:
                if gave_up.is_set():  # it waited for the lock until Haiku had already moved on
                    return
                try:
                    sent_before.append(self.sent)
                    request = self._late_note() + self._new_lines() + "\n\n" + CONSULT_REQUEST.format(question=question, owner=self.owner)
                    answer.append(parse_advice(self.ask(request))["note"])
                except Exception:
                    pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(seconds)
        if thread.is_alive() or not answer:
            gave_up.set()
            if not sent_before:  # never started: nothing for Sonnet to be told
                return None
            # Haiku goes on without it. The next request tells Sonnet, and a review due meanwhile stops this one.
            self.late = {"question": question, "sent_before": sent_before[0] if sent_before else self.sent, "thread": thread}
            return None
        return answer[0] or None

    def _name_check(self):
        """On a call Pat answered: one list of advice, and the name they gave, when it isn't the saved one, as a question."""
        if not self.caller_id:
            return ""
        # The note shows both as one Advice line, and Sonnet kept saying the same deadline in each.
        advice = (f"\nLeave follow_up empty: important_details holds what else {self.owner} should know or do, "
                  "beyond the answers, each thing once.")
        return advice + self._contact_check()

    def _contact_check(self):
        """The name they gave, when it isn't the saved one, as a question for the owner."""
        name, label = self.caller_id
        if label:
            greeted = f", so Haiku greeted them as {name}" if name else ""
            return (f"\nThe caller is saved in {self.owner}'s contacts as \"{label}\"{greeted}. If they gave a different name for "
                    f"themselves, add a \"contact\" field to the JSON: \"Says they are <their name>; saved as {label}: update the "
                    f"contact?\" Otherwise leave it out, and say nothing about names elsewhere.")
        return (f"\nThis number isn't in {self.owner}'s contacts. If they said who they are, add a \"contact\" field to the JSON: "
                f"\"Says they are <their name>: add to contacts?\" Otherwise leave it out, and say nothing about names elsewhere.")

    def final_report(self, reason, seconds=45, also=""):
        """The result for whoever asked for the call. None if Sonnet can't produce one in time.
        also: more asked in the same request, such as phone_memory.NOTES_REQUEST."""
        report = []

        def run():
            if not self._take_lock(wait=seconds):
                return
            try:
                request = (f"{self._late_note()}{self._new_lines()}\n\n{REPORT_REQUEST.format(reason=reason, owner=self.owner)}"
                           f"{self._name_check()}{also}\n\n{date_lines()} {WRITE_REAL_DATES}")
                report.append(real_dates(_first_json(self.ask(request))))
            except Exception:
                pass
            finally:
                self.lock.release()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(seconds)
        return report[0] if report else None
