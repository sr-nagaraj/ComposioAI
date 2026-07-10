"""Shared domain enums."""

from enum import StrEnum


class ResearchStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"


class EvidenceType(StrEnum):
    OFFICIAL_DOCS = "official_docs"
    GITHUB_REPO = "github_repo"
    BLOG_POST = "blog_post"
    THIRD_PARTY = "third_party"
    OTHER = "other"
