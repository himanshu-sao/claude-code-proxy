"""Suite-wide safety net for the opt-in signal log.

src/__init__.py runs ``load_dotenv(override=True)``, so a developer .env with
``AUTO_SIGNAL_LOG=1`` would make any test that posts to /v1/messages append to the real
logs/auto_signal.log. This autouse fixture removes the env var, redirects the log path to a
tmp file and resets the logger handlers before and after every test. Tests that need the log
simply set AUTO_SIGNAL_LOG themselves (and may re-patch ``_log_path``) after this runs.
"""

import pytest

from src.core import signal_log


@pytest.fixture(autouse=True)
def _isolate_signal_log(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTO_SIGNAL_LOG", raising=False)
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(tmp_path / "conftest_auto_signal.log"))
    signal_log.reset_for_tests()
    yield
    signal_log.reset_for_tests()
