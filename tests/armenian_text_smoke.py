from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.additional_tts import normalize_russian_for_pocket_tts


def main() -> None:
    source = '  Привет\u00a0—  как дела?  Сегодня   отличный день…  '
    actual = normalize_russian_for_pocket_tts(source)
    expected = 'привет - как дела? сегодня отличный день...'
    if actual != expected:
        raise AssertionError(f'Unexpected Armenian TTS Russian normalization: {actual!r}')
    uppercase = normalize_russian_for_pocket_tts("ПРИВЕТ, ЁЖИК!")
    if uppercase != "привет, ёжик!":
        raise AssertionError(f'Russian Pocket TTS text must be lowercase: {uppercase!r}')
    if not any('а' <= char.lower() <= 'я' for char in actual):
        raise AssertionError('Russian Cyrillic text was lost during normalization')
    print('PASS: Armenian Pocket TTS Russian text normalization')


if __name__ == '__main__':
    main()
