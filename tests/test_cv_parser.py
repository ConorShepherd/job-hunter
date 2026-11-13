import pytest

from cv_parser import CVParseError, extract_text


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class FakeReader:
    def __init__(self, pages):
        self.pages = pages


def test_extract_text_concatenates_pages(monkeypatch):
    monkeypatch.setattr(
        "cv_parser.PdfReader",
        lambda path: FakeReader([FakePage("Page one text"), FakePage("Page two text")]),
    )

    text = extract_text("fake.pdf")

    assert "Page one text" in text
    assert "Page two text" in text


def test_extract_text_raises_on_empty_pdf(monkeypatch):
    monkeypatch.setattr(
        "cv_parser.PdfReader",
        lambda path: FakeReader([FakePage(""), FakePage(None)]),
    )

    with pytest.raises(CVParseError, match="No extractable text"):
        extract_text("scanned.pdf")


def test_extract_text_raises_on_open_failure(monkeypatch):
    def broken_reader(path):
        raise ValueError("corrupt file")

    monkeypatch.setattr("cv_parser.PdfReader", broken_reader)

    with pytest.raises(CVParseError, match="Could not open"):
        extract_text("bad.pdf")
