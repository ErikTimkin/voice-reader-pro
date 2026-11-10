# Voice Reader Pro

Локальная озвучка текста в голосовом канале Discord. Для синтеза не требуется внешний TTS API.

## Доступные голоса

- **Обычный мужской** — Silero v5.6, диктор Aidar.
- **Обычный женский** — Silero v5.6, диктор Baya.
- **Милый голос** — Silero v5.6, диктор Xenia.
- **Желейный медведь** — Xenia с локальной обработкой FFmpeg: повышенная высота тона и мультяшная подача. Это стилизация, а не копирование конкретного исполнителя.
- **Армянский акцент** — Pocket TTS, русская речь с восточноармянским мужским тембром. Используется tri-language модель Armenian + Russian + English и короткий синтетический мужской армянский референс из CC0-набора. Русские числа нормализуются общим модулем приложения.

## Модели и атрибуция

- **Armenian Pocket TTS fine-tune by mnjoyan:** https://huggingface.co/mnjoyan/pocket-tts-armenian. Лицензия модели, указанная автором, — CC BY 4.0.
- **Синтетический армянский голосовой образец:** https://huggingface.co/datasets/ErikMkrtchyan/Hy-Generated-audio-data-2. Страница набора указывает CC0 1.0.
- **Pocket TTS upstream code by Kyutai:** MIT License.
- **Silero voice model:** см. уведомление voices/SILERO_MODEL_NOTICE.txt; перед коммерческим использованием проверьте условия лицензии.

## Запуск

Распакуйте архив целиком и запустите VoiceReaderPro.exe. Не удаляйте рядом лежащие папки voices и tools. Все пять доступных голосов работают локально.
