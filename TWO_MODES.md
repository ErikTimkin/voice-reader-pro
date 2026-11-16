# Voice Reader Pro — two isolated modes

The Windows desktop executable starts with a mode selector:

1. **Text bot** — the restored Build #348 text-to-speech application.
2. **Live voice changer** — a microphone effects processor.

## Process and code isolation

The selector launches the chosen mode as a separate OS process. The text bot continues
to use its existing application, service, TTS profiles, web UI and Discord connection.
The live mode has its own entry point, UI and audio engine.

The live audio path is:

```
Physical microphone
  -> Voice Reader Pro live process
  -> microphone DSP (48 kHz / 20 ms target blocks)
  -> CABLE Input (VB-Audio Virtual Cable)
  -> CABLE Output (Windows recording device)
  -> Discord microphone selection
```

The live process does not use the text bot's Discord bot token, TTS service, web server,
voice profiles or message queue. The text process does not import the live audio engine.
A static architecture test checks these import boundaries.

## Live effects in this milestone

- Normal, Low, High, Radio, Robot and Demon presets.
- Manual pitch, bass, treble and distortion controls.
- Input/output device selection and refresh.
- Device routing through VB-CABLE.
- A stateful pitch shifter with recent-input history to reduce silence when switching effects.
- Error handling that silences output rather than emitting corrupted audio.

VB-CABLE is a separate Windows driver. It is not silently installed by the application.
Choose **CABLE Input** as the live app's output and **CABLE Output** as the microphone
in Discord. Use headphones to avoid feedback.

## AI voice conversion

The DSP effects are not neural voice conversion. An offline AI voice-conversion engine
requires a compatible model, runtime, model license and a real-time latency test on the
target PC. The previous TeraTTS experiment is text-to-speech, not microphone-to-microphone
voice conversion, so it must not be presented as live AI conversion. Keep that engine
separate from the stable text selector until an actual offline voice-conversion model
has been selected and validated.

## Build and validation

CI checks source compilation, text-bot regressions, DSP output/pitch, variable audio block
sizes, live effect changes, callback timing, mode-selector UI and the existing packaged
text voices. CI cannot prove physical microphone routing or Discord sound quality. Those
last checks require a Windows PC with the actual microphone, VB-CABLE and Discord.
