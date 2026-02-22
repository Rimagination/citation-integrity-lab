from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


STATUS_LABELS = {
    "green": "完全支持 / 健康",
    "yellow": "部分支持 / 存在偏差",
    "red": "不支持 / 高风险",
    "white": "证据不足",
}


class ParseRequest(BaseModel):
    text: str = Field(..., min_length=1, description="原始输入文本（正文 + 参考文献）")
    mode: Literal["full", "references"] = Field(
        default="full",
        description="核查模式：full=正文+参考文献，references=仅参考文献",
    )


class ParseReference(BaseModel):
    ref_id: str
    raw: str
    index: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    first_author: Optional[str] = None
    year: Optional[int] = None
    title: Optional[str] = None
    doi: Optional[str] = None


class CitationAnchor(BaseModel):
    anchor_id: str
    marker: str
    start: int
    end: int
    linked_ref_ids: List[str] = Field(default_factory=list)
    context: str
    claim: str


class ParseResult(BaseModel):
    body_text: str
    reference_text: str
    references: List[ParseReference]
    anchors: List[CitationAnchor]


class OfficialMetadata(BaseModel):
    source: str
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None


class ConflictItem(BaseModel):
    field: str
    user_value: Optional[str]
    official_value: Optional[str]
    similarity: Optional[float] = None
    level: str = "warning"


class DimensionResult(BaseModel):
    status: str
    label: str
    score: float
    reason: str


class ReferenceVerification(BaseModel):
    ref_id: str
    status: str
    label: str
    reason: str
    score: float
    official: Optional[OfficialMetadata] = None
    conflicts: List[ConflictItem] = Field(default_factory=list)
    sources_found: List[str] = Field(default_factory=list)
    source_links: Dict[str, str] = Field(default_factory=dict)
    citation_suggestions: Dict[str, str] = Field(default_factory=dict)


class AnchorVerification(BaseModel):
    anchor_id: str
    marker: str
    linked_ref_ids: List[str] = Field(default_factory=list)
    overall_status: str
    overall_label: str
    context: str
    claim: str
    dimensions: Dict[str, DimensionResult]
    linked_reference_results: List[ReferenceVerification] = Field(default_factory=list)
    radar: Dict[str, float]


class AnalyzeResult(BaseModel):
    parse: ParseResult
    reference_results: Dict[str, ReferenceVerification]
    anchor_results: List[AnchorVerification]


class MetadataVerifyRequest(BaseModel):
    references: List[ParseReference]


class SupportVerifyRequest(BaseModel):
    claim: str = Field(..., min_length=1)
    abstract: Optional[str] = None
