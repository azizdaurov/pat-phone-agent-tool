"""A separate, accepted test profile. Never read or overwrite a real user's setup."""
import os
import tempfile

_previous = None
_saved = False
_previous_speech = None


def setup_profile():
    global _previous, _saved, _previous_speech
    from user_profile import UserProfile
    _previous = os.environ.get("PAT_PROFILE_PATH")
    _previous_speech = os.environ.get("PAT_SPEECH_DESCRIPTOR")
    path = os.path.join(tempfile.mkdtemp(prefix="pat-test-profile-"), "profile.json")
    os.environ["PAT_PROFILE_PATH"] = path
    os.environ["PAT_SPEECH_DESCRIPTOR"] = os.path.join(os.path.dirname(path), "speech-service.json")
    _saved = True
    profile = UserProfile()
    profile.save(name="Aziz", country="UZ", time_zone="Asia/Tashkent", date_format="dmy")
    profile.accept_terms()


def teardown_profile():
    global _saved
    if not _saved:
        return
    if _previous is None:
        os.environ.pop("PAT_PROFILE_PATH", None)
    else:
        os.environ["PAT_PROFILE_PATH"] = _previous
    if _previous_speech is None:
        os.environ.pop("PAT_SPEECH_DESCRIPTOR", None)
    else:
        os.environ["PAT_SPEECH_DESCRIPTOR"] = _previous_speech
    _saved = False
