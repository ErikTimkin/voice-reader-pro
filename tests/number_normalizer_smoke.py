import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_reader.number_normalizer import normalize_numbers_for_speech


def main() -> None:
    cases = [
        ("Мне 25 лет", "мне двадцать пять лет"),
        ("В 2026 году", "в две тысячи двадцать шесть году"),
        ("Температура -7", "температура минус семь"),
        ("Цена 3,14", "цена три целых четырнадцать сотых"),
        ("Скидка 15%", "скидка пятнадцать процентов"),
        ("Встреча в 15:30", "встреча в пятнадцать часов тридцать минут"),
        ("Дата 12.05.2026", "дата двенадцатое мая две тысячи двадцать шесть"),
    ]

    for source, expected in cases:
        actual = normalize_numbers_for_speech(source).lower()
        if actual != expected:
            raise AssertionError(f"{source!r}: expected {expected!r}, got {actual!r}")

    phone = normalize_numbers_for_speech("Позвони +7 (999) 123-45-67")
    if phone != "Позвони семь девять девять девять один два три четыре пять шесть семь":
        raise AssertionError(f"Phone number was not read digit-by-digit: {phone!r}")

    url = normalize_numbers_for_speech("Открой https://example.com/item123")
    if url != "Открой ссылка":
        raise AssertionError(f"URL was mangled while expanding numbers: {url!r}")

    print("Russian number normalization tests passed: integers, years, decimals, negative numbers, percent, time, dates and phone numbers.")


if __name__ == "__main__":
    main()
