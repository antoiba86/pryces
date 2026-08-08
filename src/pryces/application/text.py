from __future__ import annotations

# Broker CSVs are not reliably UTF-8. Horos' pasted movements table and some
# Spanish exports arrive as cp1252, where "ó" is 0xF3 and "€" is 0x80 — bytes
# that are invalid UTF-8. Decoding those with errors="ignore" *drops* them
# silently, so a header like "TIPO DE OPERACIÓN" becomes "TIPO DE OPERACIN" and
# no importer recognises the file. Transcode on the way in instead.
_ENCODINGS = ("utf-8-sig", "cp1252")

_PREVIEW_LIMIT = 200


def detect_encoding(content: bytes) -> str | None:
    """Returns the first encoding in `_ENCODINGS` that decodes `content` cleanly."""
    for encoding in _ENCODINGS:
        try:
            content.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return None


def decode_csv(content: bytes) -> str:
    """Decodes CSV bytes to text, whatever the source encoding.

    Tries UTF-8 first (BOM-aware), then cp1252 — a superset of latin-1 covering
    the Spanish accents and the euro sign brokers emit. Never raises: a binary
    file handed in during auto-detection decodes to garbage that simply fails
    the header check, which is what `can_parse` needs.
    """
    encoding = detect_encoding(content)
    if encoding is None:
        return content.decode("utf-8", errors="ignore")
    return content.decode(encoding)


def describe_content(content: bytes) -> str:
    """One-line, human-readable summary of an uploaded file, for error messages.

    Reports the detected encoding and the first line — which is the header, and
    therefore the single most useful fact when a broker silently changes its
    export format and nothing recognises the file any more.
    """
    if not content:
        return "the file is empty"
    encoding = detect_encoding(content)
    if encoding is None:
        return f"binary content ({len(content)} bytes), no text encoding detected"
    first_line = decode_csv(content).splitlines()[0].strip() if content else ""
    if not first_line:
        return f"detected encoding {encoding}, but the first line is blank"
    if len(first_line) > _PREVIEW_LIMIT:
        first_line = first_line[:_PREVIEW_LIMIT] + "…"
    return f"detected encoding {encoding}; first line: {first_line!r}"
