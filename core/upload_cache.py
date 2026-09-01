import io


def remember_upload(cache: dict, client: str, slot: str, name: str, data: bytes) -> None:
    cache.setdefault(client, {})[slot] = {"name": name, "data": data}


def resolve_upload(uploaded_file, cache: dict, client: str, slot: str):
    """Returns (file, name, from_cache) for one upload slot (e.g. "new_leads"
    or "purchased_report") on the Run Check page -- a freshly uploaded file
    this rerun if there is one, otherwise whatever was uploaded for this
    same client earlier in the session. Streamlit's file_uploader widget
    doesn't survive a page navigation (the widget fully unmounts), so
    without this a client's file would need re-selecting every time you
    left Run Check and came back. Caching by client name means switching
    to a different client naturally starts empty for that client rather
    than carrying over the wrong file, and switching back restores what
    was already selected.

    `cache` is the caller's persistent dict (Run Check passes in a
    st.session_state-backed dict) -- kept as a plain parameter rather than
    reading session_state directly so this stays testable without
    Streamlit.
    """
    if uploaded_file is not None:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        remember_upload(cache, client, slot, uploaded_file.name, data)
        uploaded_file.seek(0)
        return uploaded_file, uploaded_file.name, False
    cached = cache.get(client, {}).get(slot)
    if cached is None:
        return None, None, False
    buf = io.BytesIO(cached["data"])
    buf.name = cached["name"]
    return buf, cached["name"], True
