"""Write job listings to a single self-contained, sortable/filterable HTML file."""
from __future__ import annotations

import html as html_lib


def _format_salary(row: dict) -> str:
    lo, hi = row.get("salary_min"), row.get("salary_max")
    if not lo and not hi:
        return ""
    lo_str = f"{lo:,.0f}" if lo else "?"
    hi_str = f"{hi:,.0f}" if hi else "?"
    return f"{lo_str} - {hi_str}"


def _row_html(row: dict, show_score: bool) -> str:
    title = html_lib.escape(row.get("title", ""))
    company = html_lib.escape(row.get("company", ""))
    location = html_lib.escape(row.get("location", ""))
    source = html_lib.escape(row.get("source", ""))
    url = html_lib.escape(row.get("url", ""), quote=True)
    posted = html_lib.escape((row.get("created") or "")[:10])
    salary = html_lib.escape(_format_salary(row))
    rationale = row.get("rationale")

    title_cell = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>'
    if rationale:
        title_cell += f'<div class="rationale">{html_lib.escape(rationale)}</div>'

    score_cell = ""
    if show_score:
        score = row.get("score")
        score_cell = f'<td data-sort="{score if score is not None else -1}"><span class="score">{score if score is not None else ""}</span></td>'

    return (
        "<tr>"
        f"{score_cell}"
        f'<td data-sort="{title.lower()}">{title_cell}</td>'
        f'<td data-sort="{company.lower()}">{company}</td>'
        f'<td data-sort="{location.lower()}">{location}</td>'
        f'<td data-sort="{row.get("salary_min") or 0}">{salary}</td>'
        f'<td data-sort="{source.lower()}">{source}</td>'
        f'<td data-sort="{posted}">{posted}</td>'
        "</tr>"
    )


def write_report(rows: list[dict], path: str = "results.html", title: str = "Job Search Results") -> None:
    show_score = any(row.get("score") is not None for row in rows)
    if show_score:
        rows = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)

    score_header = '<th data-type="num">Score</th>' if show_score else ""
    body_rows = "\n".join(_row_html(row, show_score) for row in rows)

    html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html_lib.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
          background: #fff; color: #111; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1a1a1a; color: #eee; }}
    th {{ border-bottom-color: #444 !important; }}
    td {{ border-bottom-color: #2a2a2a !important; }}
    #filter {{ background: #2a2a2a; color: #eee; border-color: #444; }}
    .rationale {{ color: #aaa !important; }}
    .score {{ background: #14532d !important; color: #bbf7d0 !important; }}
  }}
  h1 {{ font-size: 18px; margin: 0 0 16px; }}
  #filter {{ padding: 8px 10px; width: 100%; max-width: 320px; margin-bottom: 16px;
             font-size: 14px; border: 1px solid #ccc; border-radius: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; padding: 8px; border-bottom: 2px solid #ddd; cursor: pointer;
        user-select: none; white-space: nowrap; }}
  th:hover {{ opacity: 0.7; }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; vertical-align: top; }}
  a {{ color: inherit; text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}
  .rationale {{ font-weight: normal; font-size: 12.5px; color: #666; margin-top: 2px; max-width: 480px; }}
  .score {{ display: inline-block; background: #dcfce7; color: #166534; font-weight: 700;
            padding: 2px 8px; border-radius: 999px; }}
</style>
</head>
<body>
<h1>{html_lib.escape(title)} &mdash; {len(rows)} results</h1>
<input id="filter" type="text" placeholder="Filter by title or company...">
<table id="results">
<thead>
<tr>
  {score_header}
  <th>Title</th>
  <th>Company</th>
  <th>Location</th>
  <th data-type="num">Salary</th>
  <th>Source</th>
  <th>Posted</th>
</tr>
</thead>
<tbody>
{body_rows}
</tbody>
</table>
<script>
document.getElementById('filter').addEventListener('input', function () {{
  var q = this.value.toLowerCase();
  document.querySelectorAll('#results tbody tr').forEach(function (tr) {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}});

document.querySelectorAll('#results th').forEach(function (th, idx) {{
  th.addEventListener('click', function () {{
    var tbody = document.querySelector('#results tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    var numeric = th.dataset.type === 'num';
    var asc = th.dataset.asc !== 'true';
    document.querySelectorAll('#results th').forEach(function (h) {{ delete h.dataset.asc; }});
    th.dataset.asc = asc;
    rows.sort(function (a, b) {{
      var av = a.children[idx].dataset.sort, bv = b.children[idx].dataset.sort;
      if (numeric) {{ av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; return asc ? av - bv : bv - av; }}
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(function (tr) {{ tbody.appendChild(tr); }});
  }});
}});
</script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
