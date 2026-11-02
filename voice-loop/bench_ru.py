"""Time Russian speech candidates on this CPU.

  bench_ru.py tts   time the kept Piper voices; saves clips and listening samples
  bench_ru.py stt   compare speech-to-text models on those clips (run tts first)
  bench_ru.py loop  run whole Russian turns with real Claude replies
"""
import difflib
import glob
import logging
import os
import re
import statistics
import subprocess
import sys
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
SAMPLES = os.path.join(HERE, "samples")
CLIPS = os.path.join(SAMPLES, "ru_clips")
SENTENCES = [
    "Столица Канады это Оттава, а самый большой город страны это Торонто.",
    "Попробуйте ложиться спать и вставать в одно и то же время каждый день.",
    "Листья меняют цвет осенью, потому что деревья перестают вырабатывать хлорофилл.",
    "Белый рис обычно варится около пятнадцати минут на медленном огне.",
    "Перед утренней пробежкой хорошо съесть банан или немного овсянки.",
]
NUMBERS = "Ответ девяносто два, а в 2024 году это было 17 процентов, сказал Google."


def save_wav(path, audio, rate):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(path, "rb") as f:
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        return pcm.astype(np.float32) / 32767, f.getframerate()


def piper_engine(voice):
    from piper import PiperVoice
    folder = os.path.join(MODELS, "piper")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{voice}.onnx")
    if not os.path.exists(path):
        subprocess.run([sys.executable, "-m", "piper.download_voices", voice, "--data-dir", folder], check=True)
    model = PiperVoice.load(path)

    def synth(text):
        for chunk in model.synthesize(text):
            yield chunk.audio_float_array

    return synth, model.config.sample_rate


def bench_tts():
    os.makedirs(CLIPS, exist_ok=True)
    engines = [
        ("piper_irina", lambda: piper_engine("ru_RU-irina-medium")),
        ("piper_ruslan", lambda: piper_engine("ru_RU-ruslan-medium")),
    ]
    for name, build in engines:
        try:
            t0 = time.perf_counter()
            synth, rate = build()
            load = time.perf_counter() - t0
            for _ in synth("Готово."):
                pass
            firsts, speeds, clips = [], [], []
            for i, text in enumerate(SENTENCES):
                t0 = time.perf_counter()
                first, pieces = None, []
                for piece in synth(text):
                    first = first or time.perf_counter() - t0
                    pieces.append(piece)
                total = time.perf_counter() - t0
                audio = np.concatenate(pieces)
                firsts.append(first)
                speeds.append(len(audio) / rate / total)
                clips.append(audio)
                save_wav(os.path.join(CLIPS, f"{name}__{i}.wav"), audio, rate)
            numbers = np.concatenate(list(synth(NUMBERS)))
            save_wav(os.path.join(CLIPS, f"{name}__numbers.wav"), numbers, rate)
            save_wav(os.path.join(SAMPLES, f"ru_{name}.wav"), np.concatenate(clips), rate)
            xs = sorted(firsts)
            print(f"{name:<18} load {load:5.1f}s  first audio median {statistics.median(xs):.3f}s "
                  f"slowest {xs[-1]:.3f}s  speed {statistics.median(speeds):5.1f}x real time  {rate} Hz", flush=True)
        except Exception as error:
            print(f"{name:<18} FAILED: {str(error)[:200]}", flush=True)


def bench_loop():
    import voice_loop as vl
    questions = [
        "Какая столица у Канады?",
        "Дай один совет, как лучше сосредоточиться на учёбе.",
        "Почему осенью листья меняют цвет?",
        "Сколько времени варится белый рис?",
        "Какое упражнение помогает при боли в спине?",
        "Кто написал роман Преступление и наказание?",
        "Как далеко находится Луна от Земли?",
        "Что лучше съесть перед утренней пробежкой?",
    ]
    voice = vl.PiperVoice()
    mouth = vl.Mouth(voice, play=False)
    speech_voice = vl.PiperVoice("ruslan")
    ear = vl.BatchEar(mic=False)
    brain = vl.Brain("ru")
    t0 = time.perf_counter()
    brain.warm_up()
    print(f"Claude ready in {time.perf_counter() - t0:.2f}s", flush=True)
    stages = {"transcript": [], "word": [], "sentence": [], "audio": []}
    for question in questions:
        clip = np.concatenate(list(speech_voice.stream(question, vl.threading.Event())))
        ear.prepare()
        ear.feed_block(clip, speech_voice.sample_rate)
        time.sleep(len(clip) / speech_voice.sample_rate)
        marks = {"release": time.perf_counter()}
        heard = ear.end(tail=0)
        marks["transcript"] = time.perf_counter()
        reply = []
        original_say = mouth.say

        def say(text, token, on_first_audio=None):
            reply.append(text)
            original_say(text, token, on_first_audio)

        mouth.say = say
        vl.run_turn(brain, mouth, heard, marks, mouth.token, show=False)
        mouth.say = original_say
        for stage, values in stages.items():
            values.append(marks[stage] - marks["release"])
        print(f"  {marks['audio'] - marks['release']:.2f}s | heard: {heard} | reply: {' '.join(reply)}", flush=True)
    brain.close()
    print("\nseconds after key release (no key tail, no speaker delay):")
    for stage, values in stages.items():
        xs = sorted(values)
        print(f"  {stage:<12} median {statistics.median(xs):.3f}  fastest {xs[0]:.3f}  slowest {xs[-1]:.3f}", flush=True)


def words(text):
    return re.findall(r"[а-я0-9]+", text.lower().replace("ё", "е"))


def missed(reference, heard):
    a, b = words(reference), words(heard)
    matched = sum(m.size for m in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return 1 - matched / max(1, len(a))


def bench_stt():
    import onnx_asr
    clips = sorted(glob.glob(os.path.join(CLIPS, "*__[0-9].wav")))
    loaded = [(os.path.basename(p), *read_wav(p)) for p in clips]
    total_audio = sum(len(a) / r for _, a, r in loaded)
    print(f"{len(loaded)} clips, {total_audio:.0f}s of generated speech", flush=True)
    for name in ["gigaam-v3-ctc"]:
        try:
            t0 = time.perf_counter()
            try:
                model = onnx_asr.load_model(name, quantization="int8")
                quant = "int8"
            except Exception:
                model = onnx_asr.load_model(name)
                quant = "default"
            load = time.perf_counter() - t0
            model.recognize(loaded[0][1], sample_rate=loaded[0][2])
            times, errors, by_voice = [], [], {}
            for filename, audio, rate in loaded:
                t0 = time.perf_counter()
                heard = model.recognize(audio, sample_rate=rate)
                times.append(time.perf_counter() - t0)
                error = missed(SENTENCES[int(filename.split("__")[1][0])], heard)
                errors.append(error)
                by_voice.setdefault(filename.split("__")[0], []).append(error)
            xs = sorted(times)
            speed = total_audio / sum(times)
            print(f"\n{name} ({quant}): load {load:.1f}s, median {statistics.median(xs):.3f}s, slowest {xs[-1]:.3f}s, "
                  f"{speed:.0f}x real time, words missed {100 * statistics.mean(errors):.1f}%", flush=True)
            print("  by voice: " + ", ".join(f"{v} {100 * statistics.mean(e):.0f}%" for v, e in by_voice.items()), flush=True)
            print("  sample:", heard, flush=True)
            for path in sorted(glob.glob(os.path.join(CLIPS, "*__numbers.wav"))):
                audio, rate = read_wav(path)
                print(f"  numbers via {os.path.basename(path).split('__')[0]}: {model.recognize(audio, sample_rate=rate)}", flush=True)
        except Exception as error:
            print(f"\n{name} FAILED: {str(error)[:300]}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.INFO)
    {"tts": bench_tts, "stt": bench_stt, "loop": bench_loop}[sys.argv[1]]()
