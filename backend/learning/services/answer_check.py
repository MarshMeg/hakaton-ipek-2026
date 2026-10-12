"""Проверка ответов с учётом особенностей удмуртского алфавита.

В удмуртском алфавите пять дополнительных букв: Ӝ Ӟ Ӥ Ӧ Ӵ. На обычной клавиатуре их нет,
поэтому ребёнок часто пишет «ж» вместо «ӝ» или «о» вместо «ӧ». Такой ответ мы не считаем
ошибкой, а засчитываем как «почти верно» и показываем правильное написание.
"""

import enum
import re
import unicodedata

# Удмуртская буква -> «обычная» кириллическая, которой её обычно заменяют.
UDMURT_TO_PLAIN = {"ӝ": "ж", "ӟ": "з", "ӥ": "и", "ӧ": "о", "ӵ": "ч"}

# Похожие латинские символы, которые встречаются при вводе с латинской раскладки.
LOOKALIKES = {"ö": "ӧ", "ë": "ё", "ï": "ӥ"}

_PUNCTUATION = re.compile(r"[^\w\s-]", re.UNICODE)
_SPACES = re.compile(r"\s+")


class Verdict(enum.StrEnum):
    CORRECT = "correct"
    ALMOST = "almost"  # верно, но удмуртские буквы заменены обычными
    WRONG = "wrong"


def normalize(text: str) -> str:
    """Канонический вид ответа: NFC, нижний регистр, без пунктуации и лишних пробелов."""
    # NFC склеивает «о + U+0308» в один символ «ӧ».
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(LOOKALIKES.get(ch, ch) for ch in text)
    text = text.replace("ё", "е")
    text = _PUNCTUATION.sub("", text)
    return _SPACES.sub(" ", text).strip()


def to_plain(text: str) -> str:
    """Заменяет удмуртские буквы на обычные — для сравнения «почти верных» ответов."""
    return "".join(UDMURT_TO_PLAIN.get(ch, ch) for ch in text)


def check_answer(given: str, accepted: list[str]) -> Verdict:
    """Сравнивает ответ игрока со списком допустимых ответов."""
    given_norm = normalize(given)
    if not given_norm:
        return Verdict.WRONG
    accepted_norm = [normalize(a) for a in accepted]
    if given_norm in accepted_norm:
        return Verdict.CORRECT
    if to_plain(given_norm) in {to_plain(a) for a in accepted_norm}:
        return Verdict.ALMOST
    return Verdict.WRONG
