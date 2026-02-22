from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from .models import CitationAnchor, ParseReference, ParseResult


DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
REF_START_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[\.\)]|（(\d+)）)\s*")
YEAR_RE = re.compile(r"(19|20)\d{2}[a-z]?", re.IGNORECASE)
NUMERIC_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,;\-]\s*\d+)*)\]")
AUTHOR_YEAR_CITATION_RE = re.compile(
    r"\(([A-Z][^()]{1,100}?,\s*(?:19|20)\d{2}[a-z]?)\)"
)
AUTHOR_YEAR_CITATION_CN_RE = re.compile(
    r"（([^（）]{1,100}?[，,]\s*(?:19|20)\d{2}[a-z]?)）"
)
SENTENCE_RE = re.compile(r"[^。！？!?\.]+[。！？!?\.]?")


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _is_reference_like(line: str) -> bool:
    candidate = line.strip()
    if not candidate:
        return False
    has_year = bool(YEAR_RE.search(candidate))
    has_doi = bool(DOI_RE.search(candidate))
    starts_with_index = bool(REF_START_RE.match(candidate))
    has_author_signal = bool(
        re.search(r"\bet al\.|\b[A-Z][a-z]+,\s*[A-Z]|&| and ", candidate)
    )
    return (starts_with_index and has_year) or (has_year and (has_author_signal or has_doi))


def _is_header_like(line: str) -> bool:
    candidate = line.strip()
    if not candidate:
        return False
    if _is_reference_like(candidate) or REF_START_RE.match(candidate):
        return False
    compact = re.sub(r"[\s:：\-\(\)（）\[\]\{\}\.]+", "", candidate.lower())
    header_keywords = (
        "references",
        "reference",
        "bibliography",
        "参考文献",
        "文献清单",
        "参考书目",
    )
    return any(keyword in compact for keyword in header_keywords)


def _reference_density(lines: Sequence[str], start_idx: int, nonempty_window: int = 5) -> int:
    count = 0
    seen = 0
    for probe in range(start_idx, len(lines)):
        stripped = lines[probe].strip()
        if not stripped:
            continue
        seen += 1
        if _is_reference_like(stripped):
            count += 1
        if seen >= nonempty_window:
            break
    return count


def _find_reference_start(lines: Sequence[str]) -> int | None:
    # Prefer explicit section headers.
    for idx, line in enumerate(lines):
        if _is_header_like(line):
            return idx + 1

    # Handle references-only input that starts from the first non-empty line.
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        if _is_reference_like(line) and _reference_density(lines, idx, nonempty_window=4) >= 2:
            return idx
        break

    # Fallback: detect the first dense reference-like block.
    for idx in range(len(lines)):
        current_line = lines[idx]
        if not _is_reference_like(current_line):
            continue
        if REF_START_RE.match(current_line.strip()):
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if idx == 0 or not prev or _is_header_like(prev):
                return idx
            nonempty_tail = [line.strip() for line in lines[idx:] if line.strip()]
            if len(nonempty_tail) <= 2 and all(_is_reference_like(item) for item in nonempty_tail):
                return idx
        if _reference_density(lines, idx, nonempty_window=5) >= 2:
            return idx
    return None


def split_body_and_references(text: str) -> Tuple[str, str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return "", ""

    lines = normalized.split("\n")
    split_at = _find_reference_start(lines)
    if split_at is None:
        return normalized, ""

    body = "\n".join(lines[:split_at]).strip()
    references = "\n".join(lines[split_at:]).strip()
    return body, references


def _extract_year(cleaned_ref: str) -> int | None:
    match = YEAR_RE.search(cleaned_ref)
    if not match:
        return None
    try:
        return int(match.group(0)[:4])
    except ValueError:
        return None


def _extract_authors_segment(cleaned_ref: str, year: int | None) -> str:
    if year is None:
        return cleaned_ref.split(".", maxsplit=1)[0].strip()
    match = YEAR_RE.search(cleaned_ref)
    if not match:
        return cleaned_ref.split(".", maxsplit=1)[0].strip()
    return cleaned_ref[: match.start()].strip(" .;,")


def _extract_authors(authors_segment: str) -> List[str]:
    if not authors_segment:
        return []

    chunks = re.split(r"\s*(?:;|&| and )\s*", authors_segment, flags=re.IGNORECASE)
    authors: List[str] = []
    for chunk in chunks:
        candidate = chunk.strip(" .,")
        if candidate:
            authors.append(candidate)
    return authors


def _extract_first_author(authors: List[str]) -> str | None:
    if not authors:
        return None
    first = authors[0]
    if "," in first:
        return first.split(",", maxsplit=1)[0].strip()
    return first.split(" ", maxsplit=1)[0].strip()


def _extract_title(cleaned_ref: str, year: int | None) -> str | None:
    remainder = cleaned_ref
    if year is not None:
        match = YEAR_RE.search(cleaned_ref)
        if match:
            remainder = cleaned_ref[match.end() :]

    remainder = re.sub(r"^[\)\].,:;\s-]+", "", remainder)
    parts = [part.strip(" .") for part in re.split(r"\.\s+", remainder) if part.strip(" .")]
    if not parts:
        return None

    for part in parts:
        if not part.lower().startswith("doi") and len(part) >= 8:
            return part
    return parts[0]


def parse_reference_section(reference_text: str) -> List[ParseReference]:
    if not reference_text.strip():
        return []

    lines = [line.rstrip() for line in reference_text.split("\n")]
    entries: List[str] = []
    current: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_header_like(stripped):
            continue
        if REF_START_RE.match(stripped):
            if current:
                entries.append(_clean_spaces(" ".join(current)))
            current = [stripped]
        else:
            if current:
                current.append(stripped)
            else:
                # Handles references that are not explicitly indexed.
                current = [stripped]
    if current:
        entries.append(_clean_spaces(" ".join(current)))

    references: List[ParseReference] = []
    for fallback_idx, entry in enumerate(entries, start=1):
        index: int | None = None
        cleaned = entry

        index_match = REF_START_RE.match(entry)
        if index_match:
            for group in index_match.groups():
                if group:
                    index = int(group)
                    break
            cleaned = entry[index_match.end() :].strip()

        doi_match = DOI_RE.search(cleaned)
        doi = doi_match.group(1) if doi_match else None
        year = _extract_year(cleaned)
        authors_segment = _extract_authors_segment(cleaned, year)
        authors = _extract_authors(authors_segment)
        first_author = _extract_first_author(authors)
        title = _extract_title(cleaned, year)
        ref_index = index if index is not None else fallback_idx
        ref_id = str(ref_index)

        references.append(
            ParseReference(
                ref_id=ref_id,
                raw=entry,
                index=ref_index,
                authors=authors,
                first_author=first_author,
                year=year,
                title=title,
                doi=doi,
            )
        )

    return references


def _sentence_spans(text: str) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    for match in SENTENCE_RE.finditer(text):
        segment = match.group(0)
        if segment.strip():
            spans.append((match.start(), match.end(), segment.strip()))
    if not spans and text.strip():
        spans.append((0, len(text), text.strip()))
    return spans


def _context_for_span(
    sentence_spans: Sequence[Tuple[int, int, str]],
    start: int,
    marker: str,
) -> Tuple[str, str]:
    if not sentence_spans:
        return "", ""

    idx = 0
    for probe, (seg_start, seg_end, _) in enumerate(sentence_spans):
        if seg_start <= start < seg_end:
            idx = probe
            break

    snippets: List[str] = []
    if idx > 0:
        snippets.append(sentence_spans[idx - 1][2])
    snippets.append(sentence_spans[idx][2])
    if idx + 1 < len(sentence_spans):
        snippets.append(sentence_spans[idx + 1][2])

    context = _clean_spaces(" ".join(snippets))
    claim = _clean_spaces(sentence_spans[idx][2].replace(marker, ""))
    return context, claim


def _parse_numeric_marker(marker_body: str) -> List[int]:
    refs: List[int] = []
    chunks = re.split(r"\s*[,;]\s*", marker_body)
    for chunk in chunks:
        token = chunk.strip()
        if not token:
            continue
        if "-" in token:
            bounds = token.split("-", maxsplit=1)
            if len(bounds) != 2:
                continue
            try:
                left = int(bounds[0].strip())
                right = int(bounds[1].strip())
            except ValueError:
                continue
            if right - left > 10:
                right = left + 10
            step_range = range(min(left, right), max(left, right) + 1)
            refs.extend(list(step_range))
            continue
        try:
            refs.append(int(token))
        except ValueError:
            continue
    return refs


def _map_author_year_to_refs(
    cite_text: str,
    references: Sequence[ParseReference],
) -> List[str]:
    year_match = YEAR_RE.search(cite_text)
    if not year_match:
        return []
    year = int(year_match.group(0)[:4])

    author_chunk = re.split(r"[，,]", cite_text, maxsplit=1)[0]
    author_chunk = author_chunk.replace("et al.", "").replace("等", "").strip()
    author_tokens = [_normalize_token(part) for part in author_chunk.split() if part.strip()]
    if not author_tokens and author_chunk:
        author_tokens = [_normalize_token(author_chunk)]

    linked: List[str] = []
    for ref in references:
        if ref.year and ref.year != year:
            continue
        haystacks = [
            _normalize_token(ref.first_author or ""),
            _normalize_token(" ".join(ref.authors)),
            _normalize_token(ref.raw),
        ]
        if not author_tokens:
            linked.append(ref.ref_id)
            continue
        if any(token and any(token in hay for hay in haystacks) for token in author_tokens):
            linked.append(ref.ref_id)
    return linked


def extract_anchors(body_text: str, references: Sequence[ParseReference]) -> List[CitationAnchor]:
    anchors: List[CitationAnchor] = []
    sentence_spans = _sentence_spans(body_text)
    occupied: List[Tuple[int, int]] = []
    anchor_counter = 1
    ref_index_map: Dict[int, str] = {
        ref.index: ref.ref_id for ref in references if ref.index is not None
    }

    for match in NUMERIC_CITATION_RE.finditer(body_text):
        start, end = match.span()
        marker = match.group(0)
        marker_refs = _parse_numeric_marker(match.group(1))
        linked = []
        for idx in marker_refs:
            mapped = ref_index_map.get(idx)
            if mapped and mapped not in linked:
                linked.append(mapped)
        context, claim = _context_for_span(sentence_spans, start, marker)
        anchors.append(
            CitationAnchor(
                anchor_id=f"A{anchor_counter}",
                marker=marker,
                start=start,
                end=end,
                linked_ref_ids=linked,
                context=context,
                claim=claim,
            )
        )
        occupied.append((start, end))
        anchor_counter += 1

    def overlaps_any(start_idx: int, end_idx: int) -> bool:
        for left, right in occupied:
            if not (end_idx <= left or start_idx >= right):
                return True
        return False

    for pattern in (AUTHOR_YEAR_CITATION_RE, AUTHOR_YEAR_CITATION_CN_RE):
        for match in pattern.finditer(body_text):
            start, end = match.span()
            if overlaps_any(start, end):
                continue
            marker = match.group(0)
            linked = _map_author_year_to_refs(match.group(1), references)
            context, claim = _context_for_span(sentence_spans, start, marker)
            anchors.append(
                CitationAnchor(
                    anchor_id=f"A{anchor_counter}",
                    marker=marker,
                    start=start,
                    end=end,
                    linked_ref_ids=linked,
                    context=context,
                    claim=claim,
                )
            )
            anchor_counter += 1

    anchors.sort(key=lambda anchor: (anchor.start, anchor.end))
    return anchors


def parse_text(text: str, mode: str = "full") -> ParseResult:
    normalized_mode = (mode or "full").strip().lower()
    if normalized_mode == "references":
        body_text = ""
        _, inferred_reference_text = split_body_and_references(text)
        reference_text = inferred_reference_text or text.replace("\r\n", "\n").strip()
    else:
        body_text, reference_text = split_body_and_references(text)

    references = parse_reference_section(reference_text)
    anchors = [] if normalized_mode == "references" else extract_anchors(body_text, references)
    return ParseResult(
        body_text=body_text,
        reference_text=reference_text,
        references=references,
        anchors=anchors,
    )
