import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def load_settings(**env):
    """Импортирует config.settings в отдельном процессе с заданным окружением."""
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=BACKEND,
        env={"PATH": "", **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("env", "ok"),
    [
        ({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": ""}, False),
        ({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "x" * 50}, True),
        ({"DJANGO_DEBUG": "1"}, True),
    ],
)
def test_secret_key_required_without_debug(env, ok):
    result = load_settings(**env)
    assert (result.returncode == 0) is ok, result.stderr
    if not ok:
        assert "DJANGO_SECRET_KEY" in result.stderr
