from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from num2words import num2words


MONTHS_GENITIVE = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

DIGIT_WORDS = (
    "ноль",
    "один",
    "два",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
)


def _cardinal(value: int | Decimal, *, gender: str | None = None) -> str:
    kwargs = {"lang": "ru"}
    if gender:
        kwargs["gender"] = gender
    return num2words(value, **kwargs)


def _plural_form(value: int, forms: tuple[str, str, str]) -> str:
    value = abs(value) % 100
    if 11 <= value <= 14:
        return forms[2]
    last = value % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def _replace_date(match: re.Match[str]) -> str:
    day, month, year = (int(part) for part in match.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1 <= year <= 9999):
        return match.group(0)

    day_words = num2words(day, lang="ru", to="ordinal", gender="n")
    year_words = _cardinal(year)
    return f"{day_words} {MONTHS_GENITIVE[month]} {year_words}"


def _replace_time(match: re.Match[str]) -> str:
    hour, minute = (int(part) for part in match.groups())
    if hour > 23 or minute > 59:
        return match.group(0)

    hour_words = _cardinal(hour)
    minute_words = _cardinal(minute, gender="f")
    hour_form = _plural_form(hour, ("час", "часа", "часов"))
    minute_form = _plural_form(minute, ("минута", "минуты", "минут"))
    return f"{hour_words} {hour_form} {minute_words} {minute_form}"


def _replace_percent(match: re.Match[str]) -> str:
    raw = match.group(1).replace(",", ".")
    try:
        value = Decimal(raw)
        words = _cardinal(value)
    except (InvalidOperation, ValueError, OverflowError):
        return match.group(0)

    if value == value.to_integral_value():
        suffix = _plural_form(int(value), ("процент", "процента", "процентов"))
    else:
        suffix = "процента"
    return f"{words} {suffix}"


def _replace_phone(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    # A 10–15 digit group separated by spaces/dashes is usually a phone number.
    if not 10 <= len(digits) <= 15:
        return raw
    return " ".join(DIGIT_WORDS[int(digit)] for digit in digits)


def _replace_number(match: re.Match[str]) -> str:
    raw = match.group(0)
    compact = raw.replace("\u00a0", "").replace(" ", "")
    compact = compact.replace(",", ".")
    try:
        value = Decimal(compact)
        if not value.is_finite():
            return raw
        return _cardinal(value)
    except (InvalidOperation, ValueError, OverflowError, NotImplementedError):
        return raw


def normalize_numbers_for_speech(text: str) -> str:
    """Convert common numeric forms to Russian words before local TTS synthesis.

    URLs and email-like tokens are excluded so digits in links/addresses are not
    spoken as giant integers. Date/time/percent/phone patterns are handled before
    the general cardinal/decimal conversion.
    """
    if not text:
        return text

    # Replace URLs with a spoken neutral word instead of reading tracking digits.
    text = re.sub(r"https?://\S+|www\.\S+", "ссылка", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "адрес электронной почты", text)

    text = re.sub(
        r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)",
        _replace_date,
        text,
    )
    text = re.sub(
        r"(?<!\d)(\d{1,2}):([0-5]\d)(?!\d)",
        _replace_time,
        text,
    )
    text = re.sub(
        r"(?<![\w])([-+]?\d+(?:[.,]\d+)?)\s*%(?!\w)",
        _replace_percent,
        text,
    )

    # Phone-like groups must be handled before general integers.
    text = re.sub(
        r"(?<!\w)\+?\d(?:[\d\s\u00a0().-]*\d){9,14}(?!\w)",
        _replace_phone,
        text,
    )

    # Keep thousands separators, but do not consume digits embedded in IDs/words.
    number_pattern = (
        r"(?<![\w/])[-+]?"
        r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)"
        r"(?:[.,]\d+)?"
        r"(?![\w/])"
    )
    return re.sub(number_pattern, _replace_number, text)
