"""A tiny in-memory stand-in for the parts of Streamlit used by ``mtwin.ui.pages``.

It lets the page code run end to end in environments where Streamlit cannot be installed.
Widgets return their default value, so the whole UI is exercised on its default path. The real
framework is covered separately by ``tests/test_app_streamlit.py`` (skipped without Streamlit).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any


class _Ctx(AbstractContextManager):
    def __exit__(self, *exc: object) -> None:
        return None


class _Recorder:
    """Collects everything that was rendered so tests can assert on it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def log(self, kind: str, payload: Any = None) -> None:
        self.calls.append((kind, payload))

    def of(self, kind: str) -> list[Any]:
        return [p for k, p in self.calls if k == kind]


class _Widgets:
    """Widget methods shared by the main area and the sidebar."""

    def __init__(self, rec: _Recorder, state: dict) -> None:
        self._rec = rec
        self.session_state = state

    # -- display
    def _display(self, kind: str):
        return lambda *a, **k: self._rec.log(kind, a[0] if a else None)

    def __getattr__(self, name: str):
        if name in {
            "write",
            "caption",
            "markdown",
            "subheader",
            "header",
            "title",
            "warning",
            "success",
            "info",
            "error",
            "dataframe",
            "pyplot",
        }:
            return self._display(name)
        raise AttributeError(name)

    def metric(self, label: str, value: str, delta: str | None = None, **_: Any) -> None:
        self._rec.log("metric", (label, value))

    def expander(self, *_: Any, **__: Any) -> _Ctx:
        return _Ctx()

    def download_button(self, label: str, data: Any, **kwargs: Any) -> bool:
        self._rec.log("download", (label, data, kwargs))
        return False

    # -- inputs
    def radio(self, label: str, options: list, **_: Any):
        return options[0]

    def selectbox(self, label: str, options: list, **_: Any):
        return options[0]

    def multiselect(self, label: str, options: list, default: list | None = None, **_: Any):
        return list(default or [])

    def slider(self, label: str, *args: Any, **kwargs: Any):
        if len(args) >= 3:
            return args[2]
        return kwargs.get("value")

    def number_input(self, label: str, *args: Any, value: float = 0.0, **_: Any):
        return value

    def button(self, *_: Any, **__: Any) -> bool:
        return False

    def columns(self, spec: int | list) -> list:
        n = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(n)]

    def tabs(self, labels: list) -> list:
        return [_Ctx() for _ in labels]


def make_streamlit() -> SimpleNamespace:
    """Build the fake module. ``module.recorder`` exposes what was rendered."""
    rec = _Recorder()
    state: dict = {}
    main = _Widgets(rec, state)
    sidebar = _Widgets(rec, state)

    def cache_decorator(*dargs: Any, **dkwargs: Any):
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        return lambda fn: fn

    module = SimpleNamespace(
        recorder=rec,
        session_state=state,
        sidebar=sidebar,
        cache_resource=cache_decorator,
        cache_data=cache_decorator,
        set_page_config=lambda **kw: rec.log("page_config", kw),
    )
    for name in dir(main):
        if not name.startswith("_") and name not in module.__dict__:
            setattr(module, name, getattr(main, name))
    for name in (
        "write",
        "caption",
        "markdown",
        "subheader",
        "header",
        "title",
        "warning",
        "success",
        "info",
        "error",
        "dataframe",
        "pyplot",
    ):
        setattr(module, name, getattr(main, name))
    return module
