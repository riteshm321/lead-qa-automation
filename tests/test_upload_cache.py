import io

from core.upload_cache import resolve_upload


class _FakeUploadedFile(io.BytesIO):
    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name


def test_resolve_upload_returns_the_freshly_uploaded_file_and_remembers_it():
    cache = {}
    uploaded = _FakeUploadedFile("leads.csv", b"a,b\n1,2")

    file, name, from_cache = resolve_upload(uploaded, cache, "Acme", "new_leads")

    assert file is uploaded
    assert name == "leads.csv"
    assert from_cache is False
    assert cache["Acme"]["new_leads"] == {"name": "leads.csv", "data": b"a,b\n1,2"}


def test_resolve_upload_falls_back_to_the_cache_when_nothing_uploaded_this_run():
    cache = {"Acme": {"new_leads": {"name": "leads.csv", "data": b"a,b\n1,2"}}}

    file, name, from_cache = resolve_upload(None, cache, "Acme", "new_leads")

    assert name == "leads.csv"
    assert from_cache is True
    assert file.read() == b"a,b\n1,2"
    assert file.name == "leads.csv"


def test_resolve_upload_returns_none_when_nothing_uploaded_and_nothing_cached():
    file, name, from_cache = resolve_upload(None, {}, "Acme", "new_leads")

    assert file is None
    assert name is None
    assert from_cache is False


def test_resolve_upload_scopes_the_cache_by_client_not_globally():
    # A file cached for one client must never leak into a different
    # client's fallback -- switching clients should only ever restore
    # that same client's own previously uploaded file, never someone else's.
    cache = {}
    resolve_upload(_FakeUploadedFile("acme.csv", b"acme-data"), cache, "Acme", "new_leads")

    file, name, from_cache = resolve_upload(None, cache, "Beta Corp", "new_leads")

    assert file is None
    assert name is None
    assert from_cache is False


def test_resolve_upload_a_fresh_upload_overwrites_the_previous_cache_entry():
    cache = {}
    resolve_upload(_FakeUploadedFile("old.csv", b"old-data"), cache, "Acme", "new_leads")

    resolve_upload(_FakeUploadedFile("new.csv", b"new-data"), cache, "Acme", "new_leads")
    file, name, from_cache = resolve_upload(None, cache, "Acme", "new_leads")

    assert name == "new.csv"
    assert file.read() == b"new-data"


def test_resolve_upload_keeps_separate_slots_per_client_independent():
    cache = {}
    resolve_upload(_FakeUploadedFile("leads.csv", b"leads-data"), cache, "Acme", "new_leads")

    file, name, from_cache = resolve_upload(None, cache, "Acme", "purchased_report")

    assert file is None
    assert from_cache is False
