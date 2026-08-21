import logging
import logging.handlers
import os

_LOG_DIR = "logs"
_LOG_PATH = os.path.join(_LOG_DIR, "app.log")
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_logger = logging.getLogger("lead_qa_automation")
_configured = False


def get_logger() -> logging.Logger:
    """The app's single shared logger, writing to a small rotating file
    under logs/ (relative to the app's working directory — the per-user
    data folder in the packaged exe, the repo root in dev). Configured
    once per process: importing this module repeatedly (e.g. every
    Streamlit script rerun re-imports core.errors, which imports this
    module) hits Python's module cache after the first time, so the
    handler is never attached twice.
    """
    global _configured
    if not _configured:
        _configured = True
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                _LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
        except OSError:
            # A file-logging setup failure (e.g. a locked-down folder) must
            # never take the app down with it — logging is a diagnostic
            # nice-to-have, not a functional dependency. Falls through with
            # no handler attached, so calls become harmless no-ops.
            pass
    return _logger
