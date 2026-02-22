from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx

from .models import (
    AnalyzeResult,
    AnchorVerification,
    ConflictItem,
    DimensionResult,
    OfficialMetadata,
    ParseReference,
    ReferenceVerification,
    STATUS_LABELS,
)
from .parser import parse_text


HTTP_HEADERS = {
    "User-Agent": "CitationAudit/0.1 (+https://example.com)",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]{2,}")
DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+")

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "by",
    "is",
    "are",
    "was",
    "were",
    "that",
    "this",
    "it",
    "we",
    "our",
    "their",
    "can",
    "could",
    "be",
    "from",
    "using",
    "use",
    "based",
    "study",
    "paper",
    "research",
    "和",
    "与",
    "以及",
    "进行",
    "研究",
    "表明",
    "可以",
    "能够",
    "一种",
    "通过",
    "对",
    "在",
    "中",
    "的",
    "了",
    "是",
}

INTENT_KEYWORDS = {
    "background": {
        "background",
        "review",
        "overview",
        "context",
        "widely",
        "背景",
        "综述",
        "概述",
        "已有研究",
        "常被",
    },
    "method": {
        "method",
        "model",
        "algorithm",
        "simulate",
        "simulation",
        "protocol",
        "parameter",
        "framework",
        "方法",
        "模型",
        "模拟",
        "机制",
        "参数",
        "引入",
    },
    "result": {
        "result",
        "increase",
        "improve",
        "improved",
        "effect",
        "significant",
        "evidence",
        "outcome",
        "results",
        "结果",
        "显著",
        "提升",
        "影响",
        "发现",
        "支持",
    },
}

NEGATION_WORDS = {
    "not",
    "no",
    "without",
    "none",
    "lack",
    "cannot",
    "can't",
    "didn't",
    "doesn't",
    "无",
    "未",
    "没有",
    "并非",
    "不",
}

DIMENSION_LABELS = {
    "metadata": {
        "green": "元数据一致",
        "yellow": "元数据存在偏差",
        "red": "核心元数据冲突",
        "white": "元数据证据不足",
    },
    "relevance": {
        "green": "语境匹配良好",
        "yellow": "语境部分匹配",
        "red": "语境相关性不足",
        "white": "相关性证据不足",
    },
    "support": {
        "green": "完全支持",
        "yellow": "部分支持/仅相关",
        "red": "不支持/可能矛盾",
        "white": "证据不足",
    },
}

SOURCE_ORDER = ["crossref", "openalex", "datacite", "semanticscholar"]
SOURCE_LABELS = {
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "datacite": "DataCite",
    "semanticscholar": "Semantic Scholar",
}
SOURCE_PRIORITY = {
    "crossref": 4,
    "openalex": 3,
    "datacite": 2,
    "semanticscholar": 1,
}

ECOLOGY_KEYWORDS = {
    "ecology",
    "ecosystem",
    "biodiversity",
    "pollinator",
    "wetland",
    "urban green",
    "green space",
    "soil carbon",
    "carbon storage",
    "forest",
    "species",
    "生态",
    "生物多样性",
    "传粉",
    "湿地",
    "绿地",
    "土壤",
    "碳",
    "森林",
    "物种",
}

MEDICAL_KEYWORDS = {
    "vaccine",
    "covid",
    "covid-19",
    "sars-cov-2",
    "mrna",
    "bnt162b2",
    "patient",
    "clinical",
    "trial",
    "hospital",
    "therapy",
    "disease",
    "infection",
    "medicine",
    "医学",
    "患者",
    "疫苗",
    "临床",
    "住院",
    "感染",
    "治疗",
    "疾病",
}

ECOLOGY_STRONG_KEYWORDS = {
    "biodiversity",
    "pollinator",
    "wetland",
    "ecosystem",
    "soil carbon",
    "urban green",
    "green space",
    "species",
    "生态",
    "生物多样性",
    "传粉",
    "湿地",
    "土壤",
    "物种",
}

MEDICAL_STRONG_KEYWORDS = {
    "covid",
    "covid-19",
    "sars-cov-2",
    "vaccine",
    "mrna",
    "bnt162b2",
    "clinical trial",
    "patient",
    "hospital",
    "医学",
    "疫苗",
    "临床",
    "患者",
    "住院",
}


def _clean_spaces(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _text_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    plain = HTML_TAG_RE.sub(" ", text)
    return _clean_spaces(plain)


def _normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    candidate = re.sub(r"^https?://(dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    match = DOI_RE.search(candidate)
    if match:
        return match.group(1).lower()
    return candidate.lower()


def _char_mix(text: str) -> Tuple[int, int]:
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    return latin, cjk


def _is_cross_lingual_pair(left: str, right: str) -> bool:
    left_latin, left_cjk = _char_mix(left or "")
    right_latin, right_cjk = _char_mix(right or "")

    left_total = max(1, left_latin + left_cjk)
    right_total = max(1, right_latin + right_cjk)
    left_cjk_ratio = left_cjk / left_total
    right_cjk_ratio = right_cjk / right_total

    # One side mostly CJK and the other mostly Latin.
    return (left_cjk_ratio >= 0.45 and right_cjk_ratio <= 0.10) or (
        right_cjk_ratio >= 0.45 and left_cjk_ratio <= 0.10
    )


def _keyword_hits(text: str, keywords: set[str]) -> int:
    lowered = (text or "").lower()
    return sum(1 for item in keywords if item in lowered)


def _detect_domain(text: str) -> str:
    cleaned = _clean_spaces(text or "")
    ecology_hits = _keyword_hits(cleaned, ECOLOGY_KEYWORDS)
    medical_hits = _keyword_hits(cleaned, MEDICAL_KEYWORDS)
    ecology_strong = _keyword_hits(cleaned, ECOLOGY_STRONG_KEYWORDS)
    medical_strong = _keyword_hits(cleaned, MEDICAL_STRONG_KEYWORDS)

    if ecology_hits >= 2 and ecology_hits >= medical_hits + 1:
        return "ecology"
    if medical_hits >= 2 and medical_hits >= ecology_hits + 1:
        return "medical"

    # Fallback for sparse abstracts: one strong domain cue and no opposite cues.
    if ecology_strong >= 1 and medical_hits == 0 and medical_strong == 0:
        return "ecology"
    if medical_strong >= 1 and ecology_hits == 0 and ecology_strong == 0:
        return "medical"

    # Long text fallback when only one side has clues.
    if len(cleaned) >= 120:
        if ecology_hits >= 1 and medical_hits == 0:
            return "ecology"
        if medical_hits >= 1 and ecology_hits == 0:
            return "medical"

    return "unknown"


def _split_sentences(text: str, min_len: int = 20) -> List[str]:
    cleaned = _clean_spaces(text)
    if not cleaned:
        return []
    raw_parts = SENTENCE_SPLIT_RE.split(cleaned)
    sentences: List[str] = []
    for part in raw_parts:
        candidate = part.strip()
        if not candidate:
            continue
        if len(candidate) < min_len:
            continue
        sentences.append(candidate)
    return sentences


def _tokens(text: str) -> List[str]:
    words = [match.group(0).lower() for match in TOKEN_RE.finditer(text or "")]
    normalized: List[str] = []
    for word in words:
        token = word
        if token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("es") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        if token in STOPWORDS or len(token) < 2:
            continue
        normalized.append(token)
    return normalized


def _cosine_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_counter = Counter(left_tokens)
    right_counter = Counter(right_tokens)
    dot = sum(left_counter[token] * right_counter[token] for token in left_counter.keys() & right_counter.keys())
    left_norm = math.sqrt(sum(value * value for value in left_counter.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counter.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _best_evidence_sentence(query: str, document: str | None) -> Tuple[str | None, float]:
    if not document:
        return None, 0.0
    sentences = _split_sentences(document)
    if not sentences:
        return None, 0.0
    best_sentence = None
    best_score = -1.0
    for sentence in sentences:
        score = _cosine_similarity(query, sentence)
        if score > best_score or (
            abs(score - best_score) <= 1e-9
            and (best_sentence is None or len(sentence) > len(best_sentence))
        ):
            best_score = score
            best_sentence = sentence
    if best_score < 0:
        return None, 0.0
    return best_sentence, best_score


def _classify_intent(text: str) -> str:
    lowered = (text or "").lower()
    counts: Dict[str, int] = {}
    for intent, words in INTENT_KEYWORDS.items():
        counts[intent] = sum(1 for word in words if word in lowered)
    best_intent = max(counts, key=counts.get) if counts else "unknown"
    if not counts or counts[best_intent] == 0:
        return "unknown"
    return best_intent


def _with_reference_hint(reason: str, reference_hint: str | None) -> str:
    if not reference_hint:
        return reason
    return f"匹配文献：{reference_hint}。 {reason}"


def _decode_openalex_abstract(indexed_abstract: dict | None) -> str | None:
    if not indexed_abstract:
        return None
    positions: List[Tuple[int, str]] = []
    for token, indexes in indexed_abstract.items():
        for pos in indexes:
            positions.append((int(pos), token))
    if not positions:
        return None
    positions.sort(key=lambda pair: pair[0])
    words = [token for _, token in positions]
    return _clean_spaces(" ".join(words))


def _extract_crossref_authors(authors_data: list | None) -> List[str]:
    if not authors_data:
        return []
    authors: List[str] = []
    for author in authors_data:
        family = (author or {}).get("family") or ""
        given = (author or {}).get("given") or ""
        joined = _clean_spaces(f"{family}, {given}".strip(" ,"))
        if joined:
            authors.append(joined)
    return authors


def _extract_openalex_authors(authorships: list | None) -> List[str]:
    if not authorships:
        return []
    authors: List[str] = []
    for authorship in authorships:
        name = (authorship.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    return authors


def _extract_datacite_authors(creators_data: list | None) -> List[str]:
    if not creators_data:
        return []
    authors: List[str] = []
    for creator in creators_data:
        name = (creator or {}).get("name")
        if not name:
            family = (creator or {}).get("familyName") or ""
            given = (creator or {}).get("givenName") or ""
            name = _clean_spaces(f"{family}, {given}".strip(" ,"))
        if name:
            authors.append(name)
    return authors


def _extract_semantic_authors(authors_data: list | None) -> List[str]:
    if not authors_data:
        return []
    authors: List[str] = []
    for author in authors_data:
        name = (author or {}).get("name")
        if name:
            authors.append(name)
    return authors


def _extract_datacite_abstract(descriptions: list | None) -> str | None:
    if not descriptions:
        return None
    for item in descriptions:
        desc_type = ((item or {}).get("descriptionType") or "").lower()
        if desc_type == "abstract":
            return _clean_spaces((item or {}).get("description") or "")
    first = (descriptions[0] or {}).get("description")
    return _clean_spaces(first or "") or None


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict | None:
    try:
        response = await client.get(url, params=params, timeout=12.0)
        if response.status_code >= 400:
            return None
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


async def _query_crossref(client: httpx.AsyncClient, reference: ParseReference) -> OfficialMetadata | None:
    doi = _normalize_doi(reference.doi)
    payload: dict | None = None
    source = "crossref"

    if doi:
        payload = await _fetch_json(client, f"https://api.crossref.org/works/{doi}")
        if payload and payload.get("message"):
            message = payload["message"]
        else:
            message = None
    else:
        if not reference.title:
            return None
        payload = await _fetch_json(
            client,
            "https://api.crossref.org/works",
            params={"query.bibliographic": reference.title, "rows": 1},
        )
        items = (payload or {}).get("message", {}).get("items", [])
        message = items[0] if items else None

    if not message:
        return None

    title = None
    title_field = message.get("title")
    if isinstance(title_field, list) and title_field:
        title = title_field[0]
    elif isinstance(title_field, str):
        title = title_field

    year = None
    issued = message.get("issued", {}).get("date-parts")
    if issued and isinstance(issued, list) and issued and issued[0]:
        try:
            year = int(issued[0][0])
        except (TypeError, ValueError):
            year = None

    journal = None
    journal_field = message.get("container-title")
    if isinstance(journal_field, list) and journal_field:
        journal = journal_field[0]
    elif isinstance(journal_field, str):
        journal = journal_field

    doi_value = _normalize_doi(message.get("DOI"))
    url = message.get("URL")
    abstract = _strip_html(message.get("abstract"))

    return OfficialMetadata(
        source=source,
        title=_clean_spaces(title or ""),
        authors=_extract_crossref_authors(message.get("author")),
        journal=_clean_spaces(journal or "") or None,
        year=year,
        doi=doi_value,
        url=url,
        abstract=abstract,
    )


async def _query_openalex(client: httpx.AsyncClient, reference: ParseReference) -> OfficialMetadata | None:
    doi = _normalize_doi(reference.doi)
    if doi:
        payload = await _fetch_json(
            client,
            "https://api.openalex.org/works",
            params={"filter": f"doi:https://doi.org/{doi}", "per-page": 1},
        )
    else:
        if not reference.title:
            return None
        payload = await _fetch_json(
            client,
            "https://api.openalex.org/works",
            params={"search": reference.title, "per-page": 1},
        )

    works = (payload or {}).get("results", [])
    if not works:
        return None
    item = works[0]

    source_meta = item.get("primary_location", {}).get("source") or {}
    journal = source_meta.get("display_name")
    doi_value = _normalize_doi(item.get("doi"))
    abstract = _decode_openalex_abstract(item.get("abstract_inverted_index"))
    url = item.get("id")
    title = item.get("display_name")
    year = item.get("publication_year")

    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None

    return OfficialMetadata(
        source="openalex",
        title=_clean_spaces(title or ""),
        authors=_extract_openalex_authors(item.get("authorships")),
        journal=_clean_spaces(journal or "") or None,
        year=year,
        doi=doi_value,
        url=url,
        abstract=abstract,
    )


async def _query_datacite(client: httpx.AsyncClient, reference: ParseReference) -> OfficialMetadata | None:
    doi = _normalize_doi(reference.doi)
    payload: dict | None = None
    data: dict | None = None

    if doi:
        payload = await _fetch_json(client, f"https://api.datacite.org/dois/{doi}")
        data = (payload or {}).get("data")
    else:
        if not reference.title:
            return None
        payload = await _fetch_json(
            client,
            "https://api.datacite.org/dois",
            params={"query": reference.title, "page[size]": 1},
        )
        data_items = (payload or {}).get("data") or []
        data = data_items[0] if data_items else None

    if not data:
        return None

    attributes = data.get("attributes") or {}
    titles = attributes.get("titles") or []
    title = None
    if titles and isinstance(titles[0], dict):
        title = titles[0].get("title")

    year = attributes.get("publicationYear")
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None

    doi_value = _normalize_doi(attributes.get("doi"))
    landing_url = attributes.get("url")
    if not landing_url and doi_value:
        landing_url = f"https://doi.org/{doi_value}"

    return OfficialMetadata(
        source="datacite",
        title=_clean_spaces(title or ""),
        authors=_extract_datacite_authors(attributes.get("creators")),
        journal=_clean_spaces(attributes.get("publisher") or "") or None,
        year=year,
        doi=doi_value,
        url=landing_url,
        abstract=_extract_datacite_abstract(attributes.get("descriptions")),
    )


async def _query_semanticscholar(
    client: httpx.AsyncClient,
    reference: ParseReference,
) -> OfficialMetadata | None:
    fields = "title,year,authors,url,abstract,externalIds,journal"
    doi = _normalize_doi(reference.doi)
    item: dict | None = None

    if doi:
        payload = await _fetch_json(
            client,
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": fields},
        )
        item = payload
    else:
        if not reference.title:
            return None
        payload = await _fetch_json(
            client,
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": reference.title, "limit": 1, "fields": fields},
        )
        candidates = (payload or {}).get("data") or []
        item = candidates[0] if candidates else None

    if not item or item.get("error"):
        return None

    journal = (item.get("journal") or {}).get("name")
    year = item.get("year")
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None

    doi_value = _normalize_doi((item.get("externalIds") or {}).get("DOI"))
    return OfficialMetadata(
        source="semanticscholar",
        title=_clean_spaces(item.get("title") or ""),
        authors=_extract_semantic_authors(item.get("authors")),
        journal=_clean_spaces(journal or "") or None,
        year=year,
        doi=doi_value,
        url=item.get("url"),
        abstract=_clean_spaces(item.get("abstract") or "") or None,
    )


def _metadata_conflicts(reference: ParseReference, official: OfficialMetadata) -> Tuple[List[ConflictItem], str, float]:
    conflicts: List[ConflictItem] = []
    critical = False

    if reference.title and official.title:
        title_sim = _text_similarity(reference.title, official.title)
        if title_sim < 0.8:
            conflicts.append(
                ConflictItem(
                    field="title",
                    user_value=reference.title,
                    official_value=official.title,
                    similarity=round(title_sim, 3),
                    level="critical",
                )
            )
            critical = True
        elif title_sim < 0.9:
            conflicts.append(
                ConflictItem(
                    field="title",
                    user_value=reference.title,
                    official_value=official.title,
                    similarity=round(title_sim, 3),
                    level="warning",
                )
            )

    if reference.year and official.year:
        year_gap = abs(reference.year - official.year)
        if year_gap > 1:
            conflicts.append(
                ConflictItem(
                    field="year",
                    user_value=str(reference.year),
                    official_value=str(official.year),
                    level="critical",
                )
            )
            critical = True
        elif year_gap == 1:
            conflicts.append(
                ConflictItem(
                    field="year",
                    user_value=str(reference.year),
                    official_value=str(official.year),
                    level="warning",
                )
            )

    user_doi = _normalize_doi(reference.doi)
    official_doi = _normalize_doi(official.doi)
    if user_doi and official_doi and user_doi != official_doi:
        conflicts.append(
            ConflictItem(
                field="doi",
                user_value=user_doi,
                official_value=official_doi,
                level="critical",
            )
        )
        critical = True

    if reference.first_author and official.authors:
        official_first_author = official.authors[0].split(",", maxsplit=1)[0]
        author_sim = _text_similarity(reference.first_author, official_first_author)
        if author_sim < 0.5:
            conflicts.append(
                ConflictItem(
                    field="first_author",
                    user_value=reference.first_author,
                    official_value=official_first_author,
                    similarity=round(author_sim, 3),
                    level="warning",
                )
            )

    if critical:
        return conflicts, "red", 0.2
    if conflicts:
        return conflicts, "yellow", 0.6
    return conflicts, "green", 0.95


def _pick_official(
    source_metadata: Dict[str, OfficialMetadata | None],
    user_title: str | None,
) -> OfficialMetadata | None:
    candidates = [item for item in source_metadata.values() if item]
    if not candidates:
        return None

    def _score(meta: OfficialMetadata) -> Tuple[float, int, int]:
        title_score = _text_similarity(user_title or "", meta.title or "")
        source_weight = SOURCE_PRIORITY.get(meta.source, 0)
        has_abstract = 1 if meta.abstract else 0
        # Prefer records with abstracts so relevance/support checks are available.
        return title_score, has_abstract, source_weight

    if user_title:
        return max(candidates, key=_score)

    return max(
        candidates,
        key=lambda meta: (
            SOURCE_PRIORITY.get(meta.source, 0),
            1 if meta.abstract else 0,
            1 if meta.doi else 0,
        ),
    )


def _sources_found(source_metadata: Dict[str, OfficialMetadata | None]) -> List[str]:
    found: List[str] = []
    for source in SOURCE_ORDER:
        if source_metadata.get(source):
            found.append(source)
    return found


def _build_source_links(
    source_metadata: Dict[str, OfficialMetadata | None],
    reference: ParseReference,
) -> Dict[str, str]:
    links: Dict[str, str] = {}

    preferred_doi = None
    for source in SOURCE_ORDER:
        candidate = source_metadata.get(source)
        if candidate and candidate.doi:
            preferred_doi = _normalize_doi(candidate.doi)
            break
    if not preferred_doi:
        preferred_doi = _normalize_doi(reference.doi)

    crossref_meta = source_metadata.get("crossref")

    if preferred_doi:
        links["doi"] = f"https://doi.org/{quote(preferred_doi, safe='/')}"
        if crossref_meta and crossref_meta.url:
            links["crossref"] = crossref_meta.url
        else:
            # For DOI records, prefer the landing URL (publisher page) over search results.
            links["crossref"] = links["doi"]
        links["openalex"] = f"https://openalex.org/works?filter=doi:{quote(preferred_doi, safe='')}"
        links["datacite"] = f"https://commons.datacite.org/doi.org/{quote(preferred_doi, safe='/')}"
        links["semanticscholar"] = (
            "https://www.semanticscholar.org/search?q="
            f"{quote(preferred_doi, safe='')}"
        )
    elif crossref_meta and crossref_meta.url:
        links["crossref"] = crossref_meta.url
    elif reference.title:
        links["crossref"] = (
            "https://search.crossref.org/?q="
            f"{quote(reference.title, safe='')}"
        )

    openalex_meta = source_metadata.get("openalex")
    if openalex_meta and openalex_meta.url:
        links["openalex"] = openalex_meta.url

    datacite_meta = source_metadata.get("datacite")
    if datacite_meta and datacite_meta.doi:
        links["datacite"] = f"https://commons.datacite.org/doi.org/{quote(datacite_meta.doi, safe='/')}"

    semanticscholar_meta = source_metadata.get("semanticscholar")
    if semanticscholar_meta and semanticscholar_meta.url:
        links["semanticscholar"] = semanticscholar_meta.url

    return links


def _source_summary(found_sources: Sequence[str]) -> str:
    if not found_sources:
        return "无"
    names = [SOURCE_LABELS.get(item, item) for item in found_sources]
    return " / ".join(names)


async def verify_reference_metadata(
    reference: ParseReference,
    client: httpx.AsyncClient,
) -> ReferenceVerification:
    crossref_task = asyncio.create_task(_query_crossref(client, reference))
    openalex_task = asyncio.create_task(_query_openalex(client, reference))
    datacite_task = asyncio.create_task(_query_datacite(client, reference))
    semanticscholar_task = asyncio.create_task(_query_semanticscholar(client, reference))
    crossref_meta, openalex_meta, datacite_meta, semanticscholar_meta = await asyncio.gather(
        crossref_task,
        openalex_task,
        datacite_task,
        semanticscholar_task,
    )

    source_metadata = {
        "crossref": crossref_meta,
        "openalex": openalex_meta,
        "datacite": datacite_meta,
        "semanticscholar": semanticscholar_meta,
    }
    found_sources = _sources_found(source_metadata)
    source_links = _build_source_links(source_metadata, reference)

    official = _pick_official(source_metadata, reference.title)
    if not official:
        return ReferenceVerification(
            ref_id=reference.ref_id,
            status="red",
            label=DIMENSION_LABELS["metadata"]["red"],
            reason=(
                "Crossref / OpenAlex / DataCite / Semantic Scholar 均未命中，"
                "疑似捏造或信息缺失。"
            ),
            score=0.05,
            official=None,
            conflicts=[],
            sources_found=found_sources,
            source_links=source_links,
        )

    conflicts, status, score = _metadata_conflicts(reference, official)
    source_summary = _source_summary(found_sources)
    if status == "green" and len(found_sources) >= 2:
        score = min(0.99, score + 0.02 * (len(found_sources) - 1))
    elif status == "yellow" and len(found_sources) >= 3:
        score = min(0.75, score + 0.05)

    if status == "green":
        reason = f"多源命中（{source_summary}），标题/年份整体匹配。"
    elif status == "yellow":
        reason = f"多源命中（{source_summary}），但存在字段偏差（{len(conflicts)} 项）。"
    else:
        reason = f"多源命中（{source_summary}），但核心字段冲突（{len(conflicts)} 项）。"

    return ReferenceVerification(
        ref_id=reference.ref_id,
        status=status,
        label=DIMENSION_LABELS["metadata"][status],
        reason=reason,
        score=score,
        official=official,
        conflicts=conflicts,
        sources_found=found_sources,
        source_links=source_links,
    )


def evaluate_relevance(
    context: str,
    reference_text: str | None,
    reference_hint: str | None = None,
) -> DimensionResult:
    if not reference_text:
        return DimensionResult(
            status="white",
            label=DIMENSION_LABELS["relevance"]["white"],
            score=0.35,
            reason=_with_reference_hint("未获取到官方摘要，无法做语义相关性与引用意图判断。", reference_hint),
        )

    similarity = _cosine_similarity(context, reference_text)
    evidence_sentence, evidence_score = _best_evidence_sentence(context, reference_text)
    context_intent = _classify_intent(context)
    abstract_intent = _classify_intent(reference_text)
    is_background_context = context_intent == "background"
    strict_mode = context_intent in {"result", "method"}
    cross_lingual = _is_cross_lingual_pair(context, reference_text)

    # Tightened red condition: relevance alone turns red only with extremely low match
    # in strict contexts; background references are treated more leniently.
    if cross_lingual and similarity < 0.08 and evidence_score < 0.08:
        status = "white"
    elif is_background_context:
        if similarity < 0.03 and evidence_score < 0.03:
            status = "yellow"
        elif similarity < 0.10:
            status = "yellow"
        else:
            status = "green"
    else:
        if strict_mode and similarity < 0.02 and evidence_score < 0.03:
            status = "red"
        elif similarity < 0.12:
            status = "yellow"
        else:
            status = "green"

    if (
        status == "green"
        and context_intent != "unknown"
        and abstract_intent != "unknown"
        and context_intent != abstract_intent
    ):
        status = "yellow"

    score = max(0.0, min(1.0, (similarity * 0.7 + evidence_score * 0.3) * 3.2))
    if cross_lingual and status == "white":
        score = max(score, 0.45)
    evidence_text = _clean_spaces(evidence_sentence or "")
    if evidence_text:
        evidence_text = evidence_text[:180]
    reason = (
        f"语义相似度={similarity:.3f}，证据句匹配={evidence_score:.3f}，"
        f"上下文意图={context_intent}，摘要意图={abstract_intent}，跨语言={cross_lingual}。"
        f"证据句：{evidence_text or '未提取到稳定证据句'}。"
    )
    return DimensionResult(
        status=status,
        label=DIMENSION_LABELS["relevance"][status],
        score=round(score, 3),
        reason=_with_reference_hint(reason, reference_hint),
    )


def _has_negation(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in NEGATION_WORDS)


def _fuzzy_coverage(claim_tokens: Iterable[str], abstract_tokens: Iterable[str]) -> float:
    claim_set = set(claim_tokens)
    abstract_set = set(abstract_tokens)
    if not claim_set or not abstract_set:
        return 0.0

    matched = 0
    for claim_token in claim_set:
        if claim_token in abstract_set:
            matched += 1
            continue
        if any(SequenceMatcher(None, claim_token, abstract_token).ratio() >= 0.84 for abstract_token in abstract_set):
            matched += 1
    return matched / len(claim_set)


def evaluate_support(
    claim: str,
    reference_text: str | None,
    context: str | None = None,
    reference_hint: str | None = None,
) -> DimensionResult:
    if not reference_text:
        return DimensionResult(
            status="white",
            label=DIMENSION_LABELS["support"]["white"],
            score=0.35,
            reason=_with_reference_hint("仅凭当前信息无法判断断言支持度。", reference_hint),
        )

    similarity = _cosine_similarity(claim, reference_text)
    evidence_sentence, evidence_score = _best_evidence_sentence(claim, reference_text)
    claim_tokens = set(_tokens(claim))
    abstract_tokens = set(_tokens(reference_text))
    if not claim_tokens:
        return DimensionResult(
            status="white",
            label=DIMENSION_LABELS["support"]["white"],
            score=0.35,
            reason=_with_reference_hint("未能从该引用句抽取有效断言词。", reference_hint),
        )

    coverage = _fuzzy_coverage(claim_tokens, abstract_tokens)
    negation_conflict = _has_negation(claim) != _has_negation(reference_text)

    context_intent = _classify_intent(context or claim)
    is_background_context = context_intent == "background"
    cross_lingual = _is_cross_lingual_pair(claim, reference_text)
    claim_domain = _detect_domain(_clean_spaces(f"{context or ''} {claim}"))
    reference_domain = _detect_domain(reference_text)

    if claim_domain != "unknown" and reference_domain != "unknown" and claim_domain != reference_domain:
        status = "red"
        score = 0.18
        reason = (
            f"检测到领域冲突（断言领域={claim_domain}，文献领域={reference_domain}），"
            f"覆盖率={coverage:.3f}，相似度={similarity:.3f}。"
        )
        evidence_text = _clean_spaces(evidence_sentence or "")
        if evidence_text:
            evidence_text = evidence_text[:180]
        reason = f"{reason} 证据句：{evidence_text or '未提取到稳定证据句'}。"
        return DimensionResult(
            status=status,
            label=DIMENSION_LABELS["support"][status],
            score=round(score, 3),
            reason=_with_reference_hint(reason, reference_hint),
        )

    # Tightened red condition: support turns red only when contradiction is clear
    # or in strict contexts with extremely low overlap.
    if negation_conflict and (similarity >= 0.12 or evidence_score >= 0.12):
        status = "red"
        score = 0.15
        reason = (
            f"检测到潜在否定语义冲突（相似度={similarity:.3f}, 覆盖率={coverage:.3f}, "
            f"证据句匹配={evidence_score:.3f}）。"
        )
    elif coverage >= 0.62 or (coverage >= 0.45 and (similarity >= 0.20 or evidence_score >= 0.20)):
        status = "green"
        score = 0.9
        reason = (
            f"摘要对断言关键词覆盖较高（覆盖率={coverage:.3f}, 相似度={similarity:.3f}, "
            f"证据句匹配={evidence_score:.3f}）。"
        )
    elif coverage >= 0.18 or similarity >= 0.10 or evidence_score >= 0.10:
        status = "yellow"
        score = 0.62 if not is_background_context else 0.68
        reason = (
            f"摘要与断言存在部分重叠（覆盖率={coverage:.3f}, 相似度={similarity:.3f}, "
            f"证据句匹配={evidence_score:.3f}）。"
        )
    else:
        if cross_lingual:
            status = "white"
            score = 0.45
            reason = (
                f"检测到跨语言场景，当前摘要证据不足（覆盖率={coverage:.3f}, "
                f"相似度={similarity:.3f}, 证据句匹配={evidence_score:.3f}）。"
            )
        elif is_background_context:
            status = "white"
            score = 0.45
            reason = (
                f"当前更接近背景性引用，摘要证据不足（覆盖率={coverage:.3f}, "
                f"相似度={similarity:.3f}, 证据句匹配={evidence_score:.3f}）。"
            )
        else:
            status = "yellow"
            score = 0.4
            reason = (
                f"摘要对断言支持较弱（覆盖率={coverage:.3f}, 相似度={similarity:.3f}, "
                f"证据句匹配={evidence_score:.3f}）。"
            )

    evidence_text = _clean_spaces(evidence_sentence or "")
    if evidence_text:
        evidence_text = evidence_text[:180]
    reason = f"{reason} 证据句：{evidence_text or '未提取到稳定证据句'}。"

    return DimensionResult(
        status=status,
        label=DIMENSION_LABELS["support"][status],
        score=round(score, 3),
        reason=_with_reference_hint(reason, reference_hint),
    )


def _combine_status(statuses: Sequence[str]) -> str:
    ordered = ["red", "yellow", "green", "white"]
    for status in ordered:
        if status in statuses:
            return status
    return "white"


def _overall_status(dimensions: Dict[str, DimensionResult]) -> str:
    metadata_status = dimensions["metadata"].status
    relevance_status = dimensions["relevance"].status
    support_status = dimensions["support"].status

    # Red is reserved for strong signals:
    # metadata conflicts or explicit support contradiction.
    if metadata_status == "red" or support_status == "red":
        return "red"

    # Relevance red/yellow without hard contradiction is downgraded to yellow,
    # reducing false positive "high risk" for generally-related citations.
    if relevance_status in {"red", "yellow"} or support_status in {"yellow"} or metadata_status in {"yellow"}:
        return "yellow"

    if metadata_status == "green" and (support_status == "green" or relevance_status == "green"):
        return "green"

    if metadata_status == "green" and support_status == "white" and relevance_status == "white":
        return "white"

    return "white"


def _aggregate_metadata_dimension(linked_references: Sequence[ReferenceVerification]) -> DimensionResult:
    if not linked_references:
        return DimensionResult(
            status="white",
            label=DIMENSION_LABELS["metadata"]["white"],
            score=0.35,
            reason="该引用标记未能映射到参考文献条目。",
        )

    statuses = [item.status for item in linked_references]
    status = _combine_status(statuses)
    score = sum(item.score for item in linked_references) / len(linked_references)

    if status == "green":
        reason = "映射文献元数据一致。"
    elif status == "yellow":
        reason = "映射文献中存在轻度元数据偏差。"
    else:
        reason = "映射文献包含核心元数据冲突或无法检索。"

    return DimensionResult(
        status=status,
        label=DIMENSION_LABELS["metadata"][status],
        score=round(score, 3),
        reason=reason,
    )


def _reference_text(candidate: ReferenceVerification) -> Optional[str]:
    if not candidate.official:
        return None
    title = _clean_spaces(candidate.official.title or "")
    abstract = _clean_spaces(candidate.official.abstract or "")
    if abstract and title:
        return f"{abstract} {title}"
    if abstract:
        return abstract
    if title:
        return title
    return None


def _reference_hint(candidate: ReferenceVerification) -> Optional[str]:
    title = _clean_spaces((candidate.official.title if candidate.official else "") or "")
    if title and len(title) > 88:
        title = f"{title[:85]}..."
    if title:
        return f"[{candidate.ref_id}] {title}"
    return f"[{candidate.ref_id}]"


def _select_reference_text(
    claim: str,
    context: str,
    linked_references: Sequence[ReferenceVerification],
) -> Tuple[Optional[str], Optional[str]]:
    if not linked_references:
        return None, None

    query = _clean_spaces(f"{context or ''} {claim or ''}")
    query_tokens = set(_tokens(query))
    query_domain = _detect_domain(query)
    best_candidate: Optional[ReferenceVerification] = None
    best_text: Optional[str] = None
    best_score = -1.0

    for candidate in linked_references:
        text = _reference_text(candidate)
        if not text:
            continue
        token_overlap = 0.0
        if query_tokens:
            ref_tokens = set(_tokens(text))
            token_overlap = len(query_tokens & ref_tokens) / max(1, len(query_tokens))

        score = candidate.score * 0.45 + token_overlap * 0.45
        if candidate.official and candidate.official.abstract:
            score += 0.10

        ref_domain = _detect_domain(text)
        if query_domain != "unknown" and ref_domain != "unknown":
            score += 0.08 if query_domain == ref_domain else -0.18

        if score > best_score:
            best_score = score
            best_candidate = candidate
            best_text = text

    if best_candidate:
        return best_text, _reference_hint(best_candidate)

    fallback = sorted(linked_references, key=lambda item: item.score, reverse=True)[0]
    return _reference_text(fallback), _reference_hint(fallback)


async def verify_references(references: Sequence[ParseReference]) -> Dict[str, ReferenceVerification]:
    if not references:
        return {}
    async with httpx.AsyncClient(headers=HTTP_HEADERS, follow_redirects=True) as client:
        tasks = [verify_reference_metadata(reference, client) for reference in references]
        verified = await asyncio.gather(*tasks)
    return {item.ref_id: item for item in verified}


async def analyze_text(text: str, mode: str = "full") -> AnalyzeResult:
    parsed = parse_text(text, mode=mode)
    reference_results = await verify_references(parsed.references)

    anchor_results: List[AnchorVerification] = []
    for anchor in parsed.anchors:
        linked_reference_results = [
            reference_results[ref_id]
            for ref_id in anchor.linked_ref_ids
            if ref_id in reference_results
        ]

        metadata_dimension = _aggregate_metadata_dimension(linked_reference_results)
        reference_text, reference_hint = _select_reference_text(
            claim=anchor.claim,
            context=anchor.context,
            linked_references=linked_reference_results,
        )
        relevance_dimension = evaluate_relevance(
            anchor.context,
            reference_text,
            reference_hint=reference_hint,
        )
        support_dimension = evaluate_support(
            anchor.claim,
            reference_text,
            context=anchor.context,
            reference_hint=reference_hint,
        )

        dimensions = {
            "metadata": metadata_dimension,
            "relevance": relevance_dimension,
            "support": support_dimension,
        }
        overall_status = _overall_status(dimensions)
        overall_label = STATUS_LABELS[overall_status]

        anchor_results.append(
            AnchorVerification(
                anchor_id=anchor.anchor_id,
                marker=anchor.marker,
                linked_ref_ids=anchor.linked_ref_ids,
                overall_status=overall_status,
                overall_label=overall_label,
                context=anchor.context,
                claim=anchor.claim,
                dimensions=dimensions,
                linked_reference_results=linked_reference_results,
                radar={
                    "metadata": metadata_dimension.score,
                    "relevance": relevance_dimension.score,
                    "support": support_dimension.score,
                },
            )
        )

    return AnalyzeResult(
        parse=parsed,
        reference_results=reference_results,
        anchor_results=anchor_results,
    )
