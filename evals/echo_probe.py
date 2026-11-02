"""Does a call's audio repeat itself a moment later? Echo from the second phone hearing the laptop speakers would.

Compares the loudness pattern of each speech turn with itself at lags from 0.15 to 1.5 s. Takes a saved call's WAV files.
"""
import sys
import wave

import numpy as np

sys.path.insert(0, __file__.rsplit("evals", 1)[0])
import cicero
from cicero import FRAME, MIC_RATE

ENVELOPE_STEP = 160  # 10 ms


def envelope(audio):
    count = len(audio) // ENVELOPE_STEP
    values = np.abs(audio[:count * ENVELOPE_STEP]).reshape(-1, ENVELOPE_STEP).mean(axis=1)
    return np.log(values + 1e-4)


def best_lag(audio):
    env = envelope(audio)
    best = (0.0, 0.0)
    for lag in range(15, min(150, len(env) // 2)):
        score = float(np.corrcoef(env[:-lag], env[lag:])[0, 1])
        if score > best[1]:
            best = (lag / 100, score)
    return best


for path in sys.argv[1:]:
    with wave.open(path) as f:
        audio = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    print(path[-34:])
    turns = cicero.TurnDetector(cicero.SpeechDetector())
    start = None
    for index in range(0, len(audio) - FRAME + 1, FRAME):
        event = turns.feed(audio[index:index + FRAME])
        if event == "start":
            start = index
        elif event == "end" and index - start > MIC_RATE:
            piece = audio[max(0, start - 16 * FRAME):index]
            lag, score = best_lag(piece)
            print(f"  turn {start / MIC_RATE:5.1f} s, {len(piece) / MIC_RATE:.1f} s long: best repeat at {lag:.2f} s, similarity {score:.2f}, peak {np.abs(piece).max():.2f}")
