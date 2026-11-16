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

The live-mode window has a separate **AI-преобразование (RVC)** action. It launches the
independent vc-gui.exe process from the open-source vc-rs project; it does not merge
its Rust runtime or model files into the text bot or the standard DSP engine.

On first use, download and extract a Windows GUI + CLI package from
https://github.com/shirohata/vc-rs/releases, then choose vc-gui.exe in Voice Reader Pro.
The selected path is saved locally. The RVC app guides the user through its support-model
setup; the target voice checkpoint is supplied by the user. The vc-rs project offers a
Windows ML package for broad GPU support and a TensorRT package for NVIDIA GPUs. Review
its own app and model terms before downloading or using models.

The RVC package is deliberately not silently downloaded or redistributed by this project:
it is a separate third-party application with its own licenses and model dependencies.
TeraTTS is text-to-speech, not microphone-to-microphone conversion, and is not used as a
substitute for RVC.

## Build and validation

CI checks source compilation, text-bot regressions, DSP output/pitch, variable audio block
sizes, live effect changes, callback timing, mode-selector UI and the existing packaged
text voices. CI cannot prove physical microphone routing or Discord sound quality. Those
last checks require a Windows PC with the actual microphone, VB-CABLE and Discord.
