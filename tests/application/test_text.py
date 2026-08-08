from pryces.application.text import decode_csv, describe_content, detect_encoding


class TestDecodeCsv:
    def test_decodes_utf8(self):
        assert decode_csv("TIPO DE OPERACIÓN;VL".encode("utf-8")) == "TIPO DE OPERACIÓN;VL"

    def test_strips_a_utf8_bom(self):
        assert decode_csv("﻿Fecha;ISIN".encode("utf-8")) == "Fecha;ISIN"

    def test_decodes_cp1252_instead_of_dropping_bytes(self):
        # The bug this exists to prevent: decoding cp1252 as UTF-8 with
        # errors="ignore" deletes 0xF3 and 0x80, turning the header into
        # "Tipo de operacin" so no importer recognises the file.
        content = "Tipo de operación;200,00€".encode("cp1252")

        assert content.decode("utf-8", errors="ignore") == "Tipo de operacin;200,00"
        assert decode_csv(content) == "Tipo de operación;200,00€"

    def test_never_raises_on_binary_content(self):
        # can_parse relies on this: undecodable input must yield garbage text
        # that fails the header check, not an exception.
        assert isinstance(decode_csv(bytes([0x81, 0x8D, 0x90, 0xFF])), str)


class TestDetectEncoding:
    def test_prefers_utf8(self):
        assert detect_encoding("ó".encode("utf-8")) == "utf-8-sig"

    def test_falls_back_to_cp1252(self):
        assert detect_encoding("ó".encode("cp1252")) == "cp1252"

    def test_returns_none_for_undecodable_bytes(self):
        assert detect_encoding(bytes([0x81, 0x8D, 0x90])) is None


class TestDescribeContent:
    def test_reports_the_header_line_and_encoding(self):
        description = describe_content(
            "Tipo de operación;Producto;VL\r\n1;2;3\r\n".encode("cp1252")
        )

        assert "cp1252" in description
        assert "Tipo de operación;Producto;VL" in description

    def test_reports_an_empty_file(self):
        assert describe_content(b"") == "the file is empty"

    def test_reports_a_blank_first_line(self):
        assert "first line is blank" in describe_content(b"\r\nFecha;ISIN\r\n")

    def test_reports_undecodable_content_as_binary(self):
        assert "binary content" in describe_content(bytes([0x81, 0x8D, 0x90]))

    def test_truncates_a_very_long_header(self):
        description = describe_content(("x" * 500).encode("utf-8"))

        assert "…" in description
        assert len(description) < 300
