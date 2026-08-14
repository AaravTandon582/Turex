"""Builds small, valid PDFs in memory for tests.

Checked-in binary fixtures are opaque: a reviewer cannot see what a test document contains,
and adjusting one line of it means regenerating a blob. Generating the PDF from a list of
text lines keeps each test's input visible in the test itself.

The output is an uncompressed PDF 1.4 using the base-14 Helvetica font, which every reader —
including pypdf — handles without embedded font data.
"""

from __future__ import annotations

from collections.abc import Sequence

_PAGE_WIDTH, _PAGE_HEIGHT = 612, 792
_MARGIN_LEFT, _MARGIN_TOP = 64, 728
_FONT_SIZE, _LEADING = 11, 15


def _escape(text: str) -> str:
    """Escape the characters that terminate or nest a PDF string literal."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: Sequence[str]) -> bytes:
    body = [
        "BT",
        f"/F1 {_FONT_SIZE} Tf",
        f"{_LEADING} TL",
        f"1 0 0 1 {_MARGIN_LEFT} {_MARGIN_TOP} Tm",
    ]
    for line in lines:
        # An empty line still needs a Tj so the vertical advance happens, which is what
        # gives extractors the blank line that marks a paragraph break.
        body.append(f"({_escape(line)}) Tj T*")
    body.append("ET")
    return "\n".join(body).encode("latin-1", errors="replace")


def build_pdf(pages: Sequence[Sequence[str]], *, title: str | None = None) -> bytes:
    """Render each sequence of lines as one page.

    `title` populates the document information dictionary, mirroring what a real producer
    writes — useful for testing that extraction prefers or rejects embedded metadata.
    """
    if not pages:
        raise ValueError("A PDF needs at least one page")

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # object numbers are 1-based

    font_number = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # The page tree must be numbered before its children can reference it as /Parent.
    pages_number = len(objects) + 1
    objects.append(b"")  # placeholder, filled in once the kids are known

    page_numbers: list[int] = []
    for lines in pages:
        stream = _content_stream(lines)
        contents_number = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_numbers.append(
            add(
                f"<< /Type /Page /Parent {pages_number} 0 R "
                f"/MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
                f"/Contents {contents_number} 0 R >>".encode()
            )
        )

    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[pages_number - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode()
    )

    catalog_number = add(f"<< /Type /Catalog /Pages {pages_number} 0 R >>".encode())

    info_number = None
    if title is not None:
        info_number = add(f"<< /Title ({_escape(title)}) >>".encode())

    # -- assemble the file, recording byte offsets for the cross-reference table --
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()

    trailer = f"<< /Size {len(objects) + 1} /Root {catalog_number} 0 R"
    if info_number is not None:
        trailer += f" /Info {info_number} 0 R"
    trailer += " >>"

    out += f"trailer\n{trailer}\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(out)


def build_paper_pdf(
    *,
    title: str = "A Study of Something Interesting",
    authors: str = "Ada Lovelace, Charles Babbage",
    abstract: str = (
        "We investigate whether the thing works. Our results show that under the conditions "
        "we tested, it does work, though not as reliably as prior work suggested. We release "
        "our code and data so the finding can be checked independently by other groups."
    ),
) -> bytes:
    """A two-page document shaped like a real paper: title block, abstract, numbered sections."""
    page_one = [
        title,
        authors,
        "Analytical Engine Institute",
        "",
        "Abstract",
        *_wrap(abstract),
        "",
        "1 Introduction",
        *_wrap(
            "Prior work established the baseline we build on. Several groups have reported "
            "conflicting results, which motivates a careful replication under controlled "
            "conditions."
        ),
    ]
    page_two = [
        "2 Method",
        *_wrap(
            "We ran the procedure forty times, varying only the temperature. Each run was "
            "recorded and independently scored by two annotators who did not know the "
            "condition."
        ),
        "",
        "3 Results",
        *_wrap(
            "Accuracy improved by eleven percent over the baseline. The effect held across "
            "every temperature we tested, though the margin narrowed at the extremes."
        ),
        "",
        "4 Conclusion",
        *_wrap("The thing works. Whether it works for the reason we assumed is less clear."),
    ]
    return build_pdf([page_one, page_two])


def _wrap(text: str, width: int = 78) -> list[str]:
    """Hard-wrap like a typesetter would, so tests exercise the unwrapping logic."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
