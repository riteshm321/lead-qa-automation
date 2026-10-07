"""Phone number helpers for the Lead Template column mapping's "Add a space
after the country code" option, plus detection of numbers that Excel has
already mangled (scientific notation / zeroed-out trailing digits).

Country calling codes are the full ITU-T E.164 assignment list. They form a
prefix-free code (no code is the start of another), so the longest code that
matches the start of a number is always the only one that matches.
"""
import re

COUNTRY_CALLING_CODES: frozenset[str] = frozenset({
    # Zone 1 - North American Numbering Plan (US, Canada, Caribbean)
    "1",
    # Zone 2 - mostly Africa
    "20", "211", "212", "213", "216", "218", "220", "221", "222", "223", "224", "225", "226", "227",
    "228", "229", "230", "231", "232", "233", "234", "235", "236", "237", "238", "239", "240", "241",
    "242", "243", "244", "245", "246", "247", "248", "249", "250", "251", "252", "253", "254", "255",
    "256", "257", "258", "260", "261", "262", "263", "264", "265", "266", "267", "268", "269", "27",
    "290", "291", "297", "298", "299",
    # Zones 3 and 4 - Europe
    "30", "31", "32", "33", "34", "350", "351", "352", "353", "354", "355", "356", "357", "358", "359",
    "36", "370", "371", "372", "373", "374", "375", "376", "377", "378", "379", "380", "381", "382",
    "383", "385", "386", "387", "389", "39", "40", "41", "420", "421", "423", "43", "44", "45", "46",
    "47", "48", "49",
    # Zone 5 - Mexico, Central and South America
    "500", "501", "502", "503", "504", "505", "506", "507", "508", "509", "51", "52", "53", "54", "55",
    "56", "57", "58", "590", "591", "592", "593", "594", "595", "596", "597", "598", "599",
    # Zone 6 - Southeast Asia and Oceania
    "60", "61", "62", "63", "64", "65", "66", "670", "672", "673", "674", "675", "676", "677", "678",
    "679", "680", "681", "682", "683", "685", "686", "687", "688", "689", "690", "691", "692",
    # Zone 7 - Russia and Kazakhstan
    "7",
    # Zone 8 - East Asia and special services
    "800", "808", "81", "82", "84", "850", "852", "853", "855", "856", "86", "870", "878", "880",
    "881", "882", "883", "886", "888",
    # Zone 9 - West, Central and South Asia, Middle East
    "90", "91", "92", "93", "94", "95", "960", "961", "962", "963", "964", "965", "966", "967", "968",
    "970", "971", "972", "973", "974", "975", "976", "977", "979", "98", "991", "992", "993", "994",
    "995", "996", "998",
})

_PHONE_COLUMN_WORDS = {"phone", "phones", "telephone", "tel", "mobile", "cell", "whatsapp", "phoneno", "phonenumber"}
_CONTACT_NUMBER_WORDS = {"number", "no", "num", "nbr"}
_SCIENTIFIC = re.compile(r"^\s*[+-]?\d+(\.\d+)?[eE][+]?\d+\s*$")


def is_phone_column(column_name) -> bool:
    """Whether a template column looks like a phone number column (Phone,
    Phone Number, Contact Number, Mobile, Work Phone, Tel, ...)."""
    words = re.findall(r"[a-z]+", str(column_name or "").lower())
    if any(w in _PHONE_COLUMN_WORDS or "phone" in w for w in words):
        return True
    # "Contact" alone or "Contact Number"/"Contact No", never "Contact Email".
    return "contact" in words and (words == ["contact"] or any(w in _CONTACT_NUMBER_WORDS for w in words))


def split_country_code(digits: str) -> tuple[str, str] | None:
    """(country code, national number) for an all-digit international
    number, or None when no country code matches or the rest is too short
    to be a real number."""
    for length in (3, 2, 1):
        code = digits[:length]
        if code in COUNTRY_CALLING_CODES:
            rest = digits[length:]
            if 4 <= len(rest) and len(digits) <= 15:
                return code, rest
            return None
    return None


def add_space_after_country_code(value) -> object:
    """'917020209586' -> '91 7020209586', '+917020209586' -> '+91 7020209586'.
    Anything already spaced/formatted, blank, non-numeric, or with no
    recognizable country code is returned unchanged."""
    if value is None:
        return value
    text = str(value).strip()
    if not text or " " in text:
        return value
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]  # a number that went through a float column
    prefix = ""
    if text.startswith("+"):
        prefix, text = "+", text[1:]
    elif text.startswith("00"):
        prefix, text = "00", text[2:]
    if not text.isdigit():
        return value
    split = split_country_code(text)
    if split is None:
        return value
    code, rest = split
    return f"{prefix}{code} {rest}"


def looks_excel_mangled(value) -> bool:
    """True for a phone value Excel has already damaged: scientific notation
    (9.17E+11) or 5+ trailing zeros, which is what's left once Excel has
    rounded a long number and saved it back to CSV."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if _SCIENTIFIC.match(text):
        return True
    digits = re.sub(r"\D", "", text)
    return len(digits) >= 10 and digits.endswith("00000")
