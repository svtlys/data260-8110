
import contextvars

from sqlalchemy import event

from db import engine

_query_log = contextvars.ContextVar("query_log", default=None)


@event.listens_for(engine, "before_cursor_execute")
def _log_query(conn, cursor, statement, parameters, context, executemany):
    log = _query_log.get()
    if log is not None:
        log.append(statement)


class CountQueries:
    """Context manager: counts SQL statements executed inside the `with` block."""

    def __enter__(self):
        self._log = []
        self._token = _query_log.set(self._log)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _query_log.reset(self._token)

    @property
    def count(self):
        return len(self._log)