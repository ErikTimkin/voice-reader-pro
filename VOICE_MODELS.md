# Voice pack sources

This branch keeps the existing release branch untouched and exposes four selectable Russian voices.

## Voices

| UI name | Engine / speaker | Purpose |
|---|---|---|
| Обычный мужской | Silero v5.6 / `aidar` | Neutral male Russian |
| Обычный женский | Silero v5.6 / `baya` | Neutral female Russian |
| Милый голос | Silero v5.6 / `xenia` | Softer, higher female timbre |
| Армянский акцент | Pocket TTS tri-language model + prepared voice reference | Russian speech with an Eastern Armenian-accented voice |

## Armenian voice model

The Armenian model files used by the app correspond to the community release:

- Model: https://huggingface.co/mnjoyan/pocket-tts-armenian
- Runtime: https://github.com/kyutai-labs/pocket-tts
- Model card declares CC BY 4.0.
- The `tri_v1` checkpoint is described by its publisher as a tri-language Armenian + Russian + English fine-tune. It is designed for cross-lingual Russian speech and streaming output.

The app uses the local `tri_v1/model.safetensors` and `tri_v1/tokenizer_tri.model` files; it does not download model weights at runtime. The speaker reference/voice-state files remain part of the local offline voice pack. Do not replace the reference recording with a real person's voice unless that person has explicitly consented to its use.

## Startup behavior

The Armenian model is preloaded in a worker thread after the standard Silero model is ready. This moves model loading and speaker-state preparation out of the first message request and keeps heavy initialization off Discord's asyncio event loop. If Armenian model loading fails, the other three voices remain available.

## Notes

This branch is experimental until the GitHub Actions Windows package build and a real Discord voice-channel test both pass. A successful package build alone does not prove live Discord playback.
