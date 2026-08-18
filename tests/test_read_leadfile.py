import io

import openpyxl
import pandas as pd

from core.excel_io import read_leadfile


def _upload(name: str, content: bytes) -> io.BytesIO:
    f = io.BytesIO(content)
    f.name = name
    return f


def test_read_leadfile_plain_utf8_csv():
    df = read_leadfile(_upload("leads.csv", b"Email,First\nabc@x.com,Bob\n"))
    assert list(df.columns) == ["Email", "First"]
    assert df.iloc[0]["Email"] == "abc@x.com"


def test_read_leadfile_strips_utf8_bom():
    content = "Email,First\nabc@x.com,Bob\n".encode("utf-8-sig")
    df = read_leadfile(_upload("leads.csv", content))
    # A leaked BOM would show up as "﻿Email" instead of "Email".
    assert list(df.columns) == ["Email", "First"]


def test_read_leadfile_detects_semicolon_delimiter():
    df = read_leadfile(_upload("leads.csv", b"Email;First\nabc@x.com;Bob\n"))
    assert list(df.columns) == ["Email", "First"]
    assert df.iloc[0]["First"] == "Bob"


def test_read_leadfile_detects_tab_delimiter():
    df = read_leadfile(_upload("leads.csv", b"Email\tFirst\nabc@x.com\tBob\n"))
    assert list(df.columns) == ["Email", "First"]


def test_read_leadfile_falls_back_to_cp1252_for_special_characters():
    content = "Email,Company\nabc@x.com,Café Corp\n".encode("cp1252")
    df = read_leadfile(_upload("leads.csv", content))
    assert df.iloc[0]["Company"] == "Café Corp"


def test_read_leadfile_xlsx_still_works(tmp_path):
    path = tmp_path / "leads.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Email", "First"])
    ws.append(["abc@x.com", "Bob"])
    wb.save(path)

    with open(path, "rb") as fh:
        df = read_leadfile(_upload("leads.xlsx", fh.read()))

    assert list(df.columns) == ["Email", "First"]
    assert df.iloc[0]["Email"] == "abc@x.com"


def test_read_leadfile_xlsx_skips_title_row_above_real_header(tmp_path):
    # Regression test: a New Leads export with a title/instructions row
    # above the real header previously got read with header=0, so pandas
    # generated "Unnamed: 0"/"Unnamed: 1" column names from that blank title
    # row instead of the real "Email"/"First Name"/... headers below it.
    path = tmp_path / "leads.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Lead Report - Generated 2026-08-18"])
    ws.append(["Email", "First Name", "Last Name", "Company", "CID"])
    ws.append(["abc@x.com", "Bob", "Smith", "Acme", "12345"])
    wb.save(path)

    with open(path, "rb") as fh:
        df = read_leadfile(_upload("leads.xlsx", fh.read()))

    assert list(df.columns) == ["Email", "First Name", "Last Name", "Company", "CID"]
    assert df.iloc[0]["Email"] == "abc@x.com"
