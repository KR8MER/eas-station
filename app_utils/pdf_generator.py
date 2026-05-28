"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

from __future__ import annotations

"""PDF generation utilities for archival documents.

This module provides utilities for generating archival-quality PDFs directly from
database data. PDFs are generated server-side and cannot be forged since they pull
directly from the database rather than relying on client-side rendering.
"""

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _escape_pdf_text(value: str) -> str:
    """Escape special characters for PDF text content."""
    # Newlines must be removed before backslash-escaping to avoid broken
    # content-stream string literals.  NOAA/IPAWS alert descriptions often
    # contain embedded \r\n or \n paragraph breaks which, if left in place,
    # split the PDF operator token across lines and corrupt the stream.
    escaped = (
        value
        .replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    return escaped


def _render_pdf_page(
    lines: Sequence[str],
    *,
    font_size: int = 10,
    line_height: int = 14,
    start_y: int = 760,
    margin_x: int = 40,
    margin_bottom: int = 40,
) -> bytes:
    """Render a page of text content into PDF stream format.

    Args:
        lines: Lines of text to render
        font_size: Font size in points (default: 10)
        line_height: Space between lines in points (default: 14)
        start_y: Starting Y position from bottom (default: 760)
        margin_x: Left margin in points (default: 40)
        margin_bottom: Bottom margin in points (default: 40)

    Returns:
        PDF content stream as bytes
    """
    y = start_y
    content_lines = ["BT", f"/F1 {font_size} Tf"]

    for line in lines:
        if y < margin_bottom:
            # Page would overflow - stop here
            break
        content_lines.append(f"1 0 0 1 {margin_x} {y} Tm ({_escape_pdf_text(line)}) Tj")
        y -= line_height

    content_lines.append("ET")
    # cp1252 (Windows-1252) is the byte mapping for /WinAnsiEncoding declared
    # on the embedded fonts; it adds em/en dashes, smart quotes, ™, … etc.
    # over plain latin-1.  Unknown characters fall back to "?" rather than
    # vanishing silently.
    stream = "\n".join(content_lines).encode("cp1252", "replace")
    return stream


def _wrap_text(text: str, max_length: int = 95) -> List[str]:
    """Wrap text to fit within PDF page width.

    Args:
        text: Text to wrap
        max_length: Maximum characters per line (default: 95)

    Returns:
        List of wrapped lines
    """
    if not text:
        return [""]

    words = text.split()
    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_length = len(word)
        # +1 for space
        if current_length + word_length + (1 if current_line else 0) <= max_length:
            current_line.append(word)
            current_length += word_length + (1 if current_line else 0)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_length

    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [""]


def generate_pdf_document(
    title: str,
    sections: List[Dict[str, Any]],
    *,
    generated_timestamp: Optional[datetime] = None,
    subtitle: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> bytes:
    """Generate a complete PDF document with multiple sections.

    Args:
        title: Document title
        sections: List of sections, each with 'heading' and 'content' (list of lines or single string)
        generated_timestamp: Timestamp to show in header (default: current time)
        subtitle: Optional subtitle line
        footer_text: Optional footer text (default: system name)

    Returns:
        Complete PDF document as bytes

    Example:
        sections = [
            {
                'heading': 'Alert Information',
                'content': [
                    'Event: Severe Thunderstorm Warning',
                    'Severity: Severe',
                    'Status: Actual',
                ]
            },
            {
                'heading': 'Description',
                'content': 'A severe thunderstorm warning has been issued...'
            }
        ]
        pdf_bytes = generate_pdf_document('Alert Detail', sections)
    """
    from app_core.eas_storage import format_local_datetime, utc_now

    if generated_timestamp is None:
        generated_timestamp = utc_now()

    # Build header lines
    header_lines = [
        title,
        f"Generated: {format_local_datetime(generated_timestamp, include_utc=True)}",
    ]

    if subtitle:
        header_lines.insert(1, subtitle)

    header_lines.append("")
    header_lines.append("=" * 90)
    header_lines.append("")

    # Build body lines from sections
    body_lines: List[str] = []

    for section in sections:
        heading = section.get('heading', '')
        content = section.get('content', [])

        if heading:
            body_lines.append(heading)
            body_lines.append("-" * len(heading))

        if isinstance(content, str):
            # Wrap long text
            wrapped = _wrap_text(content)
            body_lines.extend(wrapped)
        elif isinstance(content, list):
            for line in content:
                if isinstance(line, str):
                    # Normalise line endings and split on embedded newlines so
                    # that NOAA/IPAWS multi-paragraph descriptions are rendered
                    # as separate lines rather than breaking the PDF stream.
                    sub_lines = line.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                    for sub_line in sub_lines:
                        # Wrap individual lines if needed
                        if len(sub_line) > 95:
                            wrapped = _wrap_text(sub_line)
                            body_lines.extend(wrapped)
                        else:
                            body_lines.append(sub_line)
                else:
                    body_lines.append(str(line))

        body_lines.append("")  # Blank line after section

    # Add footer if specified
    if footer_text:
        body_lines.append("")
        body_lines.append("=" * 90)
        body_lines.append(footer_text)

    all_lines = header_lines + body_lines

    # Paginate content (45 lines per page with margins)
    lines_per_page = 45
    pages: List[List[str]] = []
    current_page: List[str] = []

    for line in all_lines:
        current_page.append(line)
        if len(current_page) >= lines_per_page:
            pages.append(current_page)
            current_page = []

    if current_page:
        pages.append(current_page)

    # Build PDF structure
    objects: List[Tuple[int, bytes]] = []
    font_obj_id = 3
    page_objects: List[int] = []
    next_obj_id = 4

    for page_lines in pages:
        content_stream = _render_pdf_page(page_lines)
        content_obj_id = next_obj_id
        next_obj_id += 1

        stream_body = (
            b"<< /Length "
            + str(len(content_stream)).encode("ascii")
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        )
        objects.append((content_obj_id, stream_body))

        page_obj_id = next_obj_id
        next_obj_id += 1
        page_objects.append(page_obj_id)

        page_body = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_obj_id} 0 R /Resources << /Font << /F1 {font_obj_id} 0 R >> >> >>"
        ).encode("latin-1")
        objects.append((page_obj_id, page_body))

    # Build pages object
    pages_body = (
        "<< /Type /Pages /Count {count} /Kids [{kids}] >>".format(
            count=len(page_objects),
            kids=" ".join(f"{obj_id} 0 R" for obj_id in page_objects) or "",
        )
    ).encode("latin-1")

    # Build catalog and font
    catalog_body = b"<< /Type /Catalog /Pages 2 0 R >>"
    font_body = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    # Insert core objects at beginning
    objects.insert(0, (1, catalog_body))
    objects.insert(1, (2, pages_body))
    objects.insert(2, (font_obj_id, font_body))

    # Write PDF file
    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    xref_positions = []
    for obj_id, body in objects:
        xref_positions.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode("latin-1"))
        buffer.write(body)
        buffer.write(b"\nendobj\n")

    # Write cross-reference table
    startxref = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in xref_positions:
        buffer.write(f"{offset:010d} 00000 n \n".encode("latin-1"))

    # Write trailer
    buffer.write(b"trailer\n")
    buffer.write(
        f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
    )
    buffer.write(f"startxref\n{startxref}\n%%EOF".encode("latin-1"))

    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Table-oriented report PDFs (used for FCC compliance exports)
# ---------------------------------------------------------------------------

_PAGE_PORTRAIT: Tuple[int, int] = (612, 792)
_PAGE_LANDSCAPE: Tuple[int, int] = (792, 612)


def _approx_helvetica_width(text: str, font_size: int) -> float:
    """Rough Helvetica advance width for monospace-style truncation."""
    # Helvetica averages ~0.5em advance for most printable ASCII; this is a
    # deliberately conservative approximation since the renderer has no real
    # font metrics.
    return len(text) * font_size * 0.52


def _truncate_to_width(text: Any, max_width_pts: float, font_size: int) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if max_width_pts <= 0:
        return ""
    if _approx_helvetica_width(s, font_size) <= max_width_pts:
        return s
    # Binary-search a fitting prefix so wide characters do not blow past the
    # column boundary even though we are guessing average widths.
    ellipsis = "…"
    lo, hi = 0, len(s)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = s[:mid] + ellipsis
        if _approx_helvetica_width(candidate, font_size) <= max_width_pts:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best == 0:
        return ""
    return s[:best] + ellipsis


def _assemble_pdf(page_streams: List[bytes], page_size: Tuple[int, int]) -> bytes:
    """Wrap pre-rendered content streams into a complete PDF document."""
    page_w, page_h = page_size
    objects: List[Tuple[int, bytes]] = []
    font_obj_id = 3
    bold_font_obj_id = font_obj_id + 1
    page_objects: List[int] = []
    # IDs 1..4 are reserved for catalog, pages tree, regular font, and bold
    # font (inserted at the front below); content/page objects start at 5 to
    # avoid colliding with the bold font's object number.
    next_obj_id = bold_font_obj_id + 1

    for content_stream in page_streams:
        content_obj_id = next_obj_id
        next_obj_id += 1
        stream_body = (
            b"<< /Length "
            + str(len(content_stream)).encode("ascii")
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        )
        objects.append((content_obj_id, stream_body))

        page_obj_id = next_obj_id
        next_obj_id += 1
        page_objects.append(page_obj_id)
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {content_obj_id} 0 R "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R /F2 {bold_font_obj_id} 0 R >> >> >>"
        ).encode("latin-1")
        objects.append((page_obj_id, page_body))

    pages_body = (
        "<< /Type /Pages /Count {count} /Kids [{kids}] >>".format(
            count=len(page_objects),
            kids=" ".join(f"{obj_id} 0 R" for obj_id in page_objects),
        )
    ).encode("latin-1")

    catalog_body = b"<< /Type /Catalog /Pages 2 0 R >>"
    font_body = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    bold_body = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>"
    )

    objects.insert(0, (1, catalog_body))
    objects.insert(1, (2, pages_body))
    objects.insert(2, (font_obj_id, font_body))
    objects.insert(3, (bold_font_obj_id, bold_body))

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    xref_positions = []
    for obj_id, body in objects:
        xref_positions.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode("latin-1"))
        buffer.write(body)
        buffer.write(b"\nendobj\n")
    startxref = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in xref_positions:
        buffer.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    buffer.write(b"trailer\n")
    buffer.write(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1"))
    buffer.write(f"startxref\n{startxref}\n%%EOF".encode("latin-1"))
    return buffer.getvalue()


def generate_table_pdf(
    title: str,
    columns: Sequence[Dict[str, Any]],
    rows: Sequence[Sequence[Any]],
    *,
    subtitle: Optional[str] = None,
    summary_lines: Optional[Sequence[str]] = None,
    generated_at: Optional[datetime] = None,
    footer_text: Optional[str] = None,
    landscape: bool = True,
    empty_message: str = "No matching records during this window.",
) -> bytes:
    """Render a paginated tabular PDF report.

    ``columns`` entries accept ``label`` and an optional ``weight`` (relative
    column width).  Rows are sequences of cell values; values are stringified
    and truncated with an ellipsis when they exceed the allotted column width.
    """

    from app_core.eas_storage import utc_now

    if generated_at is None:
        generated_at = utc_now()

    page_w, page_h = _PAGE_LANDSCAPE if landscape else _PAGE_PORTRAIT
    margin_x = 36
    margin_top = 56
    margin_bottom = 44
    body_font = 9
    header_font = 9
    title_font = 16
    subtitle_font = 11
    line_height = 13

    weights = [float(c.get("weight", 1) or 1) for c in columns]
    total_weight = sum(weights) or 1.0
    available_w = page_w - 2 * margin_x
    col_widths = [w / total_weight * available_w for w in weights]
    col_x: List[float] = []
    x_cursor = float(margin_x)
    for w in col_widths:
        col_x.append(x_cursor)
        x_cursor += w

    def emit_text(content: List[str], font_alias: str, size: int, x: float, y: float, value: str) -> None:
        content.append(f"/{font_alias} {size} Tf")
        content.append(
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_pdf_text(value)}) Tj"
        )

    def render_doc_header(content: List[str], y: float) -> float:
        emit_text(content, "F2", title_font, margin_x, y, title)
        y -= title_font + 6
        if subtitle:
            emit_text(content, "F1", subtitle_font, margin_x, y, subtitle)
            y -= subtitle_font + 4
        from app_utils.time import format_local_datetime
        gen_line = f"Generated: {format_local_datetime(generated_at, include_utc=True)}"
        emit_text(content, "F1", body_font, margin_x, y, gen_line)
        y -= body_font + 8
        return y

    def render_table_header(content: List[str], y: float) -> float:
        for i, col in enumerate(columns):
            label = _truncate_to_width(col.get("label", ""), col_widths[i] - 4, header_font)
            emit_text(content, "F2", header_font, col_x[i] + 1, y, label)
        # Draw the rule just below the header baseline (clear of the descender)
        # and leave enough vertical room for the first body row's cap height so
        # the underline never crosses the row of text below it.
        content.append("ET")
        rule_y = y - 4
        content.append(f"{margin_x} {rule_y:.2f} m {page_w - margin_x} {rule_y:.2f} l S")
        content.append("BT")
        y -= line_height + 3
        return y

    def render_footer(content: List[str], page_num: int, total_pages: Optional[int]) -> None:
        footer = footer_text or "EAS Station™ — FCC Compliance Report"
        emit_text(content, "F1", 8, margin_x, 24, footer)
        if total_pages is not None:
            label = f"Page {page_num} of {total_pages}"
        else:
            label = f"Page {page_num}"
        emit_text(content, "F1", 8, page_w - margin_x - 70, 24, label)

    # Two-pass render: pass 1 figures out page count, pass 2 stamps "of N".
    row_list = list(rows)

    def _layout(total_pages: Optional[int]) -> List[bytes]:
        rendered: List[bytes] = []
        idx = 0
        page_num = 0
        n_rows = len(row_list)
        rendered_summary = False

        while True:
            page_num += 1
            content: List[str] = ["BT"]
            y = page_h - margin_top
            if page_num == 1:
                y = render_doc_header(content, y)
            else:
                emit_text(content, "F1", body_font, margin_x, y, f"{title} (continued)")
                y -= body_font + 8
            y = render_table_header(content, y)

            if n_rows == 0 and page_num == 1:
                emit_text(content, "F1", body_font, margin_x, y - 4, empty_message)
                y -= line_height + 4
            else:
                while idx < n_rows and y >= margin_bottom + line_height:
                    row = row_list[idx]
                    for i, col in enumerate(columns):
                        cell = row[i] if i < len(row) else ""
                        text_val = _truncate_to_width(cell, col_widths[i] - 4, body_font)
                        emit_text(content, "F1", body_font, col_x[i] + 1, y, text_val)
                    y -= line_height
                    idx += 1

            done = idx >= n_rows
            if done and summary_lines and not rendered_summary:
                needed = (len(summary_lines) + 1) * line_height + 12
                if y - margin_bottom < needed:
                    # Defer summary to a fresh page.
                    pass
                else:
                    y -= 6
                    content.append("ET")
                    content.append(
                        f"{margin_x} {y:.2f} m {page_w - margin_x} {y:.2f} l S"
                    )
                    content.append("BT")
                    y -= line_height
                    emit_text(content, "F2", header_font, margin_x, y, "Summary")
                    y -= line_height
                    for line in summary_lines:
                        emit_text(content, "F1", body_font, margin_x, y, str(line))
                        y -= line_height
                    rendered_summary = True

            content.append("ET")
            render_footer(content, page_num, total_pages)
            stream = "\n".join(content).encode("cp1252", "replace")
            rendered.append(stream)

            if done and (rendered_summary or not summary_lines):
                break
            # Overflow summary onto its own page.
            if done and summary_lines and not rendered_summary:
                page_num += 1
                content = ["BT"]
                y = page_h - margin_top
                emit_text(content, "F2", title_font, margin_x, y, "Summary")
                y -= title_font + 8
                for line in summary_lines:
                    emit_text(content, "F1", body_font, margin_x, y, str(line))
                    y -= line_height
                content.append("ET")
                render_footer(content, page_num, total_pages)
                rendered.append("\n".join(content).encode("cp1252", "replace"))
                rendered_summary = True
                break

        return rendered

    first_pass = _layout(None)
    page_streams = _layout(len(first_pass))
    return _assemble_pdf(page_streams, (page_w, page_h))


__all__ = ["generate_pdf_document", "generate_table_pdf"]
