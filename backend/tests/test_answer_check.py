import pytest

from learning.services.answer_check import Verdict, check_answer, normalize


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Ӧвӧл", Verdict.CORRECT),
        ("  ӧвӧл!! ", Verdict.CORRECT),  # регистр, пробелы, пунктуация
        ("ӧвӧл", Verdict.CORRECT),  # «о» + комбинирующий диакритик -> «ӧ»
        ("öвöл", Verdict.CORRECT),  # латинская «ö» с раскладки
        ("овол", Verdict.ALMOST),  # удмуртские буквы заменены обычными
        ("бен", Verdict.WRONG),
        ("", Verdict.WRONG),
    ],
)
def test_check_answer(given, expected):
    assert check_answer(given, ["Ӧвӧл"]) == expected


def test_multiple_accepted_answers():
    assert check_answer("Ӟечбуресь", ["Ӟечбур", "Ӟечбуресь!"]) == Verdict.CORRECT


def test_normalize_collapses_spaces_and_yo():
    assert normalize("Мынам   нимы  Алёна.") == "мынам нимы алена"
