"""Sonnet reading the call. It never delays speech: reviews run beside the call, and code keeps interventions rare."""
import json
import re
import threading

from call_brief import CONSULT_REQUEST, REPORT_REQUEST

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

    def __init__(self, ask, spoken, owner="Aziz"):
        self.ask = ask
        self.spoken = spoken
        self.owner = owner
        self.lock = threading.Lock()
        self.sent = 0
        self.interventions = 0
        self.reviews = 0
        self.last_turn = None

    def _new_lines(self):
        lines = self.spoken[self.sent:]
        self.sent += len(lines)
        return "\n".join(f"{who}: {text}" for who, text in lines)

    def due(self, turn):
        """Whether to read the transcript after this caller turn."""
        if self.interventions >= MAX_INTERVENTIONS or turn % REVIEW_EVERY_TURNS:
            return False
        return self.last_turn is None or turn - self.last_turn >= MIN_TURNS_BETWEEN

    def review(self, turn):
        """Returns advice. A failure here must not touch the call, so it counts as no advice."""
        if not self.lock.acquire(blocking=False):
            return dict(NONE)  # still busy with an earlier review or a question
        try:
            self.reviews += 1
            advice = parse_advice(self.ask(self._new_lines()))
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

        def run():
            with self.lock:
                try:
                    request = self._new_lines() + "\n\n" + CONSULT_REQUEST.format(question=question, owner=self.owner)
                    answer.append(parse_advice(self.ask(request))["note"])
                except Exception:
                    pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(seconds)
        return answer[0] if answer and answer[0] else None

    def final_report(self, reason, seconds=45):
        """The result for whoever asked for the call. None if Sonnet can't produce one in time."""
        report = []

        def run():
            with self.lock:
                try:
                    request = self._new_lines() + "\n\n" + REPORT_REQUEST.format(reason=reason, owner=self.owner)
                    report.append(_first_json(self.ask(request)))
                except Exception:
                    pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(seconds)
        return report[0] if report else None
