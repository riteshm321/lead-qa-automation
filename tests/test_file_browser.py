import pytest

pytest.importorskip("tkinter")

import core.file_browser as file_browser


class _FakeRoot:
    def withdraw(self):
        pass

    def wm_attributes(self, *args):
        pass

    def destroy(self):
        pass


def test_browse_for_file_returns_selected_path(monkeypatch):
    monkeypatch.setattr(file_browser.tk, "Tk", lambda: _FakeRoot())
    monkeypatch.setattr(file_browser.filedialog, "askopenfilename", lambda **kwargs: "/chosen/path.xlsx")

    result = file_browser.browse_for_file()

    assert result == "/chosen/path.xlsx"


def test_browse_for_file_returns_none_when_cancelled(monkeypatch):
    monkeypatch.setattr(file_browser.tk, "Tk", lambda: _FakeRoot())
    monkeypatch.setattr(file_browser.filedialog, "askopenfilename", lambda **kwargs: "")

    result = file_browser.browse_for_file()

    assert result is None


def test_browse_for_file_destroys_root_even_if_dialog_raises(monkeypatch):
    # Regression test: root.destroy() must run even when the dialog call
    # itself raises (e.g. a Tcl error) — otherwise every failed "Browse..."
    # click leaked a hidden Tk root permanently.
    destroyed = []

    class _TrackingFakeRoot(_FakeRoot):
        def destroy(self):
            destroyed.append(True)

    monkeypatch.setattr(file_browser.tk, "Tk", lambda: _TrackingFakeRoot())

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(file_browser.filedialog, "askopenfilename", _raise)

    with pytest.raises(RuntimeError):
        file_browser.browse_for_file()

    assert destroyed == [True]
