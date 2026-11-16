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
  -> Voice Reader Pro live process / sounddevice capture
  -> Pedalboard DSP (48 kHz preferred, 44.1 kHz fallback)
  -> CABLE Input (VB-Audio Virtual Cable)
  -> CABLE Output (Windows recording endpoint)
  -> Discord / game / OBS microphone input
```

The initial callback block is 20 ms (960 samples at 48 kHz). Actual end-to-end latency
depends on the Windows audio driver, selected devices and system load. The app does not
inject audio into Discord and does not use the text bot's Discord connection.

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
Download it only from https://vb-audio.com/Cable/, install it separately (administrator
permission may be required), and restart Windows if the new endpoints do not appear.
Choose the physical microphone as the live app's input and **CABLE Input** as its output.
Choose **CABLE Output** as the microphone in Discord or the target application. Use
headphones to avoid feedback. Do not select CABLE Output as the physical input in Voice
Reader Pro.

Live headphone monitoring is not included in this first milestone.

## AI voice conversion

AI voice conversion, voice cloning and character impersonation are not included in this
milestone. This stage focuses only on standard DSP effects and reliable microphone routing.
The previous TeraTTS experiment is text-to-speech, not microphone-to-microphone conversion,
so it is not used as a substitute for live AI conversion. A local neural RVC engine can be
evaluated only after the standard live path has passed real microphone and Discord testing.

## Build and validation

CI checks source compilation, text-bot regressions, DSP output/pitch, variable audio block
sizes, live effect changes, callback timing, mode-selector UI and the existing packaged
text voices. CI cannot prove physical microphone routing or Discord sound quality. Those
last checks require a Windows PC with the actual microphone, VB-CABLE and Discord.
