# Audio

## How sound travels

Windows handles the call's audio itself, and programs can't open it directly, so Pat goes through Windows' default
devices:

```
Them ─► Windows plays the call on the default speaker ─► Pat records that speaker (loopback) ─► recognition ─► Claude ─► speech
Them ◄─ Windows reads the default mic = CABLE Output ◄── CABLE Input ◄── Pat plays Claude's voice
```

Just before each call, Pat makes a **silent speaker** the default: a virtual speaker that plays nothing in the room but
can still be recorded. Your real microphone isn't in the call either, so you hear nothing and they hear only Claude, until
you listen in or take over. When the call ends, every default goes back. A default left on a virtual device, which plays
and records nothing while Voicemeeter is closed, is moved to your real speaker or microphone, so Zoom, Teams and WhatsApp
keep working. While the Voicemeeter app is running, Pat leaves the defaults alone, since then they were chosen on purpose.

Pat looks for a silent speaker in this order: Voicemeeter, VB-CABLE A or B, Steam Streaming Speakers, Boom Audio. To use
another, check it plays nowhere with `.venv\Scripts\python.exe evals\silent_output_probe.py "Part of its name"`, then set
`PAT_SILENT_SPEAKER` to that name. Keep the Voicemeeter app closed: if it runs, it can pass the call to your speakers.

If a call is killed, the laptop stays on the silent speaker until Pat starts again, or until:

```powershell
.venv\Scripts\python.exe pat.py restore-audio
```

## Bluetooth headphones

With Bluetooth headphones connected to the laptop, the call's audio stays on the phone: Windows reports the move to the
laptop as done and changes nothing, even when they aren't the default speaker. 14 tries over two calls never worked, so
Pat refuses to dial while one is connected. Wired headphones and the laptop's speakers are fine.

To keep Bluetooth headphones for music, turn off their calls feature: Control Panel > Devices and Printers > right-click
the headphones > Properties > Services, untick **Handsfree Telephony**. Calls then work with them connected. Close Phone
Link too: while it runs, they keep disconnecting.

## How Pat hears

Russian uses GigaAM v3 RNN-T and English Parakeet TDT v2, both on the CPU through onnx-asr, in about 0.2 s for a short
turn after the person stops. Silero VAD decides when someone starts and stops talking. Parakeet needs about 1.1 GB of
memory, GigaAM about 0.4 GB.

Word errors on 60 clips per language (200 in brackets):

| | Simulated phone line | Plus background voices |
|---|---|---|
| Russian, GigaAM RNN-T | 18.9% (16.0%) | 25.9% (23.9%) |
| Russian, GigaAM CTC, before | 20.6% (19.2%) | 31.2% (28.8%) |
| English, Parakeet v2 | 19.2% (16.2%) | 26.5% (23.5%) |
| English, Moonshine, before | 29.9% (25.8%) | 59.0% (51.1%) |

Russian clips are real phone calls (Open STT), English ones conference calls (Earnings22); the background voices were
mixed in. On seven real English turns from one of our calls Parakeet did no better than Moonshine and sometimes repeated
words. Whisper turbo tied Parakeet on English but took 8.5 s per turn. Phone audio has nothing above 4 kHz.

## Tested on real calls

Dozens of calls in November 2026, with an iPhone and an Android phone. Their logs show the call's audio reaching the loopback
recording, Claude's replies going back through VB-CABLE, the person's echo not cutting Claude off, and `h` and `p` working
mid-call.
