#!/bin/bash
# Runs every recognizer in turn, so their timings don't compete. Results resume if stopped.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUN="$ROOT/cicero/evals/stt_run.py"
MAIN="$ROOT/voice-loop/.venv/Scripts/python.exe"
WHISPER="$ROOT/stt-test-data/whisper-venv/Scripts/python.exe"
for engine in gigaam-v3-ctc gigaam-v3-rnnt gigaam-v3-e2e-rnnt t-tech/t-one alphacep/vosk-model-ru moonshine nemo-parakeet-tdt-0.6b-v2 nemo-parakeet-tdt-0.6b-v3; do
  "$MAIN" -I "$RUN" "$engine" 2>&1 | grep -v Fetching
done
for engine in whisper:models--Systran--faster-whisper-small whisper:models--mobiuslabsgmbh--faster-whisper-large-v3-turbo; do
  "$WHISPER" -I "$RUN" "$engine" 2>&1
done
