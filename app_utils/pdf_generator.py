"""PDF generation utilities for archival documents.

This module provides utilities for generating archival-quality PDFs directly from
database data. PDFs are generated server-side and cannot be forged since they pull
directly from the database rather than relying on client-side rendering.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _escape_pdf_text(value: str) -> str:
    """Escape special characters for PDF text content."""
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
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
    stream = "\n".join(content_lines).encode("latin-1", "ignore")
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
                    # Wrap individual lines if needed
                    if len(line) > 95:
                        wrapped = _wrap_text(line)
                        body_lines.extend(wrapped)
                    else:
                        body_lines.append(line)
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
    font_body = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

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


__all__ = ["generate_pdf_document"]
