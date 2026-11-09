# Voice Reader Pro

Локальная озвучка текста в голосовом канале Discord. Для работы не требуется внешний TTS API.

## Голоса

- Silero v5.6: обычный мужской и мягкий женский голоса.
- Pocket TTS Armenian by mnjoyan: русский текст с голосовым тембром восточноармянского направления. Модель обучена на армянском, русском и английском; выбор речи использует короткий синтетический образец армянского мужского голоса из CC0-набора.
- TeraTTSv2 by TeraSpace: отдельный молодой мужской русский голос ru_m5. Это самостоятельный синтезированный тембр, не имитация голоса какого-либо артиста.

## Модели и атрибуция

- TeraTTSv2 by TeraSpace: https://huggingface.co/TeraSpace/TeraTTSv2. Распространяется по условиям Open RAIL-M с дополнительным условием указания авторства для коммерческих интеграций. Полные файлы лицензии и уведомление RUAccent включены в пакет.
- Armenian Pocket TTS fine-tune by mnjoyan: https://huggingface.co/mnjoyan/pocket-tts-armenian. Лицензия модели, указанная автором, — CC BY 4.0.
- Синтетический армянский голосовой образец: https://huggingface.co/datasets/ErikMkrtchyan/Hy-Generated-audio-data-2. Страница набора указывает CC0 1.0.
- Pocket TTS upstream code by Kyutai: MIT License.
- Silero voice model: см. приложенное уведомление voices/SILERO_MODEL_NOTICE.txt.

Для коммерческого продукта, использующего TeraTTSv2, укажите в публичном описании: "Text-to-speech powered by TeraTTSv2 by TeraSpace" и дайте ссылку на модель.

## Запуск

Распакуйте архив целиком и запустите VoiceReaderPro.exe. Не удаляйте рядом лежащие папки voices, tools и samples. Дополнительные движки загружаются при первом использовании.
