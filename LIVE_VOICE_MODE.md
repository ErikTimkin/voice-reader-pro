# Live Voice Mode — first DSP milestone

This feature branch adds a second, independent mode to Voice Reader Pro. The existing
text-to-Discord mode remains in `voice_reader/core.py` and its current TTS pipeline;
the live microphone path is isolated in `live_audio.py` and `live_voice_ui.py`.

## Signal path

```
Physical microphone
  -> Voice Reader Pro / sounddevice capture
  -> Pedalboard DSP chain
  -> selected playback endpoint: CABLE Input (VB-Audio Virtual Cable)
  -> Windows recording endpoint: CABLE Output
  -> Discord / game / OBS microphone input
```

Voice Reader Pro does not inject audio into Discord and does not use the existing
Discord bot for this mode. The receiving application must be configured manually
to use **CABLE Output** as its microphone.

## First milestone

- Six DSP presets: Normal, Low, High, Radio, Robot, Demon.
- Manual controls for pitch, bass, treble, and distortion.
- Full-duplex mono processing, 48 kHz preferred with a 44.1 kHz fallback.
- A 20 ms starting block size; actual latency depends on the Windows audio driver,
  selected devices, and machine load.
- Device refresh and explicit microphone/output selection.
- No AI voice conversion in this milestone.

## Virtual cable setup

1. Download VB-CABLE only from the official site: https://vb-audio.com/Cable/
2. Install the driver using its installer with administrator permission. Windows
   may require a restart before the new endpoints appear.
3. In Voice Reader Pro, choose the physical microphone as input and
   **CABLE Input (VB-Audio Virtual Cable)** as output.
4. In Discord (or the target application), choose **CABLE Output (VB-Audio Virtual
   Cable)** as the microphone.
5. Use headphones to avoid acoustic feedback. Do not select CABLE Output as the
   physical input inside Voice Reader Pro.

The application does not silently install a kernel audio driver. Driver installation
is a separate, user-approved Windows operation.

## Current limitations

- Live monitoring to headphones is not included yet.
- AI conversion, voice cloning, and character impersonation are not included.
- Device routing and sound quality must be verified on a real Windows PC with the
  actual microphone, VB-CABLE driver, and target app. CI can test DSP processing and
  packaged UI, but cannot prove real-device latency or Discord routing.
- If the audio callback reports an error, the app silences the output and surfaces
  the error instead of sending potentially corrupted audio.

## Branch safety

Develop this mode only on the isolated live voice feature branch. Do not merge it into the
text-mode baseline until both modes pass their separate regression checks and
real-device testing. Keep the stable text-mode branch and its existing build artifact.
