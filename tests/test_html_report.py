from html_report import write_report


def _row(title="Engineer", company="Acme", score=None, rationale=None, url="https://example.com/1"):
    return {
        "title": title,
        "company": company,
        "location": "London",
        "salary_min": 90000,
        "salary_max": 100000,
        "source": "adzuna",
        "created": "2026-01-01T00:00:00Z",
        "url": url,
        "description": "desc",
        "score": score,
        "rationale": rationale,
    }


def test_write_report_creates_file(tmp_path):
    path = tmp_path / "results.html"
    write_report([_row()], path=str(path))

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "<table" in content
    assert "Engineer" in content
    assert "Acme" in content


def test_write_report_escapes_html_in_fields(tmp_path):
    path = tmp_path / "results.html"
    write_report([_row(title="<script>alert(1)</script>", company="Ac&me")], path=str(path))

    content = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content
    assert "Ac&amp;me" in content


def test_write_report_shows_score_column_when_any_row_scored(tmp_path):
    path = tmp_path / "results.html"
    write_report([_row(score=None), _row(score=88, rationale="Great fit")], path=str(path))

    content = path.read_text(encoding="utf-8")
    assert "<th data-type=\"num\">Score</th>" in content
    assert "Great fit" in content


def test_write_report_omits_score_column_when_no_scores(tmp_path):
    path = tmp_path / "results.html"
    write_report([_row(), _row()], path=str(path))

    content = path.read_text(encoding="utf-8")
    assert "<th data-type=\"num\">Score</th>" not in content


def test_write_report_sorts_scored_rows_descending(tmp_path):
    path = tmp_path / "results.html"
    write_report(
        [_row(title="Low", score=10), _row(title="High", score=90), _row(title="Mid", score=50)],
        path=str(path),
    )

    content = path.read_text(encoding="utf-8")
    assert content.index("High") < content.index("Mid") < content.index("Low")


def test_write_report_includes_result_count_in_heading(tmp_path):
    path = tmp_path / "results.html"
    write_report([_row(), _row()], path=str(path), title="My Jobs")

    content = path.read_text(encoding="utf-8")
    assert "My Jobs" in content
    assert "2 results" in content
