"""Is the estimate of what was heard fast, and does it err early? Real speech models, no phone.

Each piece of speech is cut at known moments. The audio up to the cut is transcribed to get the words really in it,
and that word count is compared with the estimate, at margin 0 and at the real margin.
"""
import logging
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numpy as np
import pat

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
RUSSIAN = [
    "Здравствуйте, звоню узнать, работает ли ваша клиника в это воскресенье и до какого часа.",
    "Спасибо, осмотр стоит сто тысяч сумов, я передам это Азизу сегодня вечером.",
    "Подскажите, пожалуйста, можно ли прийти на приём без предварительной записи.",
    "Понял, вы работаете с девяти утра до трёх часов дня, всё верно?",
]
ENGLISH = [
    "Hello, I am calling to find out whether your clinic is open this Sunday and until what time.",
    "Thank you, the check up costs one hundred thousand, and I will pass that on to Aziz this evening.",
    "Could you tell me whether it is possible to come in without making an appointment first?",
    "I understand, you are open from nine in the morning until three in the afternoon, is that right?",
]
CUTS = (0.25, 0.5, 0.75)


def words(text):
    return len(text.split())


def transcribe_ru(ear, audio):
    return ear.model.recognize(audio, sample_rate=pat.MIC_RATE).strip()


def transcribe_en(ear, audio):
    ear.prepare()
    for start in range(0, len(audio), 1024):
        ear.feed_block(audio[start:start + 1024], pat.MIC_RATE)
    return ear.end(tail=0)


def run(name, voice, ear, transcribe, texts, length_known):
    print(f"\n=== {name}")
    ahead_zero = ahead_real = total = 0
    behind = []
    rates = []
    for text in texts:
        audio = np.concatenate(list(voice.stream(text, pat.threading.Event())))
        seconds = len(audio) / voice.sample_rate
        rates.append(len(text) / seconds)
        length = seconds if length_known else len(text) / pat.SLOW_CHARS_PER_SECOND
        for cut in CUTS:
            played = seconds * cut
            prefix = pat.to_16k(audio[:int(played * voice.sample_rate)], 1, voice.sample_rate)
            actual = transcribe(ear, prefix)
            zero = pat.heard_text([[text, played, length]], margin=0)
            real = pat.heard_text([[text, played, length]])
            total += 1
            ahead_zero += words(zero) > words(actual)
            ahead_real += words(real) > words(actual)
            behind.append(words(actual) - words(real))
            print(f"  {played:4.1f}/{seconds:.1f}s audio says {words(actual):2d} words | estimate {words(zero):2d} at margin 0, {words(real):2d} at margin {pat.CUT_MARGIN_SECONDS} | {real!r}")
    print(f"  estimate ahead of the audio: margin 0: {ahead_zero}/{total}, real margin: {ahead_real}/{total}; words behind at real margin: median {int(np.median(behind))}, most {max(behind)}, least {min(behind)}")
    print(f"  speaking rate: {min(rates):.1f}-{max(rates):.1f} characters per second")


def speed(piper):
    pieces = [[RUSSIAN[0], 5.0, 5.0], [RUSSIAN[1], 5.0, 5.0], [RUSSIAN[2], 2.0, 5.0]]
    start = time.perf_counter()
    for _ in range(1000):
        pat.heard_text(pieces)
    print(f"\nEstimating what was heard: {(time.perf_counter() - start) * 1000:.0f} microseconds each")

    first_chunk = []
    all_chunks = []
    for text in RUSSIAN:
        start = time.perf_counter()
        stream = piper.stream(text, pat.threading.Event())
        next(stream)
        first_chunk.append(time.perf_counter() - start)
        list(stream)
        all_chunks.append(time.perf_counter() - start)
    print(f"Piper, one sentence: first audio {np.median(first_chunk):.3f} s, whole piece {np.median(all_chunks):.3f} s (median of {len(RUSSIAN)})")

    note = 'You were cut off during your last reply. They heard only: "Здравствуйте, звоню узнать". Say the rest again only if it still matters.'
    print(f"Note added to Haiku's next message: {len(note)} characters")


piper = pat.PiperVoice(pat.RU_TTS_VOICE)
speed(piper)
run("Russian (Piper, length known)", piper, pat.BatchEar(pat.RU_STT_MODEL, mic=False), transcribe_ru, RUSSIAN, True)
run("English (Pocket TTS, length guessed)", pat.PocketVoice(pat.TTS_LANGUAGE, pat.TTS_VOICE),
    pat.BatchEar(pat.EN_STT_MODEL, mic=False), transcribe_en, ENGLISH, False)
