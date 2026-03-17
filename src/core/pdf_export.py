from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.models import Citation, EvalResult


def markdown_to_html(markdown: str, title: str = "Research Report") -> str:
    import re

    html_content = markdown

    html_content = re.sub(
        r"^### (.+)$",
        r"<h3>\1</h3>",
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^## (.+)$",
        r"<h2>\1</h2>",
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^# (.+)$",
        r"<h1>\1</h1>",
        html_content,
        flags=re.MULTILINE,
    )

    html_content = re.sub(
        r"\*\*\*(.+?)\*\*\*",
        r"<strong><em>\1</em></strong>",
        html_content,
    )
    html_content = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        html_content,
    )
    html_content = re.sub(
        r"\*(.+?)\*",
        r"<em>\1</em>",
        html_content,
    )

    html_content = re.sub(
        r"^\- \[ \] (.+)$",
        r"<li><input type=\"checkbox\"> \1</li>",
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^\- \[x\] (.+)$",
        r"<li><input type=\"checkbox\" checked> \1</li>",
        html_content,
        flags=re.MULTILINE,
    )
    html_content = re.sub(
        r"^\- (.+)$",
        r"<li>\1</li>",
        html_content,
        flags=re.MULTILINE,
    )

    html_content = re.sub(
        r"```(\w+)?\n([\s\S]*?)```",
        r'<pre><code class="language-\1">\2</code></pre>',
        html_content,
    )

    html_content = re.sub(
        r"`([^`]+)`",
        r"<code>\1</code>",
        html_content,
    )

    html_content = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        html_content,
    )

    lines = html_content.split("\n")
    in_list = False
    processed_lines = []
    for line in lines:
        if line.startswith("<li>"):
            if not in_list:
                processed_lines.append("<ul>")
                in_list = True
            processed_lines.append(line)
        else:
            if in_list:
                processed_lines.append("</ul>")
                in_list = False
            processed_lines.append(line)
    if in_list:
        processed_lines.append("</ul>")
    html_content = "\n".join(processed_lines)

    html_content = re.sub(r"\n\n+", r"</p><p>", html_content)
    html_content = f"<p>{html_content}</p>"
    html_content = re.sub(r"<p></p>", "", html_content)
    html_content = re.sub(r"<p>(<h[1-3]>)", r"\1", html_content)
    html_content = re.sub(r"(</h[1-3]>)<\/p>", r"\1", html_content)
    html_content = re.sub(r"<p>(<ul>)", r"\1", html_content)
    html_content = re.sub(r"(</ul>)<\/p>", r"\1", html_content)
    html_content = re.sub(r"<p>(<pre>)", r"\1", html_content)
    html_content = re.sub(r"(</pre>)<\/p>", r"\1", html_content)

    return html_content


def generate_html_report(
    report: str,
    citations: list[dict[str, Any]],
    run_id: str,
) -> str:
    citations_html = ""
    for citation in citations:
        evidence = citation.get("evidence", "")
        if len(evidence) > 500:
            evidence = evidence[:500] + "..."
        citations_html += f"""
        <div class="citation">
            <div class="citation-id">[{citation.get("claim_id", "?")}]</div>
            <div class="citation-title">{citation.get("title", "Untitled")}</div>
            <div class="citation-evidence">{evidence}</div>
            <div class="citation-source">
                <a href="{citation.get("source_url", "#")}">{citation.get("provider", "Unknown")}</a>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Research Report - {run_id}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Georgia', 'Times New Roman', serif;
            line-height: 1.8;
            color: #2c2c2c;
            background: #fafafa;
            padding: 30px;
        }}
        .container {{
            max-width: 850px;
            margin: 0 auto;
            background: white;
            padding: 60px 80px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }}
        h1 {{
            color: #1a1a1a;
            border-bottom: 2px solid #333;
            padding-bottom: 20px;
            margin-bottom: 40px;
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}
        h2 {{
            color: #2c3e50;
            margin-top: 45px;
            margin-bottom: 25px;
            font-size: 24px;
            font-weight: 600;
            border-left: 4px solid #2c3e50;
            padding-left: 15px;
        }}
        h3 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            font-size: 18px;
            font-weight: 600;
        }}
        p {{
            margin-bottom: 18px;
            text-align: justify;
            font-size: 16px;
        }}
        ul, ol {{
            margin-left: 30px;
            margin-bottom: 25px;
        }}
        li {{
            margin-bottom: 10px;
            font-size: 15px;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.9em;
        }}
        pre {{
            background: #282c34;
            color: #abb2bf;
            padding: 20px;
            border-radius: 5px;
            overflow-x: auto;
            margin: 20px 0;
        }}
        pre code {{
            background: none;
            padding: 0;
            color: inherit;
        }}
        .query-box {{
            background: #f8f9fa;
            border-left: 4px solid #2c3e50;
            padding: 25px;
            margin-bottom: 40px;
            border-radius: 0 5px 5px 0;
        }}
        .query-box h3 {{
            margin-top: 0;
            color: #2c3e50;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .query-box p {{
            font-size: 18px;
            font-weight: 500;
            margin-bottom: 0;
        }}
        .citation {{
            background: #fafafa;
            border-left: 3px solid #3498db;
            padding: 20px 25px;
            margin-bottom: 20px;
            border-radius: 0 5px 5px 0;
        }}
        .citation-id {{
            font-weight: bold;
            color: #3498db;
            margin-bottom: 8px;
            font-size: 14px;
        }}
        .citation-title {{
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 16px;
        }}
        .citation-evidence {{
            font-size: 14px;
            color: #555;
            margin-bottom: 10px;
            line-height: 1.6;
        }}
        .citation-source {{
            font-size: 12px;
        }}
        .citation-source a {{
            color: #3498db;
            text-decoration: none;
        }}
        .citation-source a:hover {{
            text-decoration: underline;
        }}
        .footer {{
            margin-top: 60px;
            padding-top: 30px;
            border-top: 1px solid #ddd;
            text-align: center;
            font-size: 12px;
            color: #888;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        {markdown_to_html(report)}

        <h2>Sources & Citations</h2>
        {citations_html}

        <div class="footer">
            <p>Generated: {datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            <p>Run ID: {run_id}</p>
            <p>Cloud Hive - AI Research Engine</p>
        </div>
    </div>
</body>
</html>"""
    return html


def convert_html_to_pdf(html: str, output_path: Path) -> Path:
    try:
        import weasyprint

        weasyprint.HTML(string=html).write_pdf(output_path)
    except ImportError as e:
        raise ImportError(
            "WeasyPrint is required for PDF generation. Install with: pip install weasyprint"
        ) from e
    return output_path


def export_report_to_pdf(
    report: str,
    citations: list[Citation],
    eval_result: EvalResult | None,
    run_id: str,
    output_dir: Path,
) -> Path:
    citations_data = [c.model_dump() for c in citations]

    html = generate_html_report(report, citations_data, run_id)

    pdf_path = output_dir / f"{run_id}.pdf"
    convert_html_to_pdf(html, pdf_path)
    return pdf_path
