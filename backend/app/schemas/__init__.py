"""Public schema surface for the FinSight API."""

from app.schemas.analysis import (
    AnalysisFilter,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisResult,
    DimensionValue,
    FinancialMetric,
)
from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    RootResponse,
)
from app.schemas.dataset import (
    Budget,
    FinancialPeriod,
    Transaction,
    Vendor,
)
from app.schemas.dataset_api import (
    ColumnSchema,
    DatasetListResponse,
    DatasetSummary,
    IntegrityCheck,
)
from app.schemas.evidence import BreakdownEvidence, EvidenceItem, EvidencePackage
from app.schemas.question import (
    Answer,
    AnswerListResponse,
    Explanation,
    QuestionInterpretation,
    QuestionRequest,
)

__all__ = [
    "AnalysisFilter",
    "AnalysisPlan",
    "AnalysisRequest",
    "AnalysisResult",
    "Answer",
    "AnswerListResponse",
    "BreakdownEvidence",
    "Budget",
    "ColumnSchema",
    "DatasetListResponse",
    "DatasetSummary",
    "DimensionValue",
    "ErrorDetail",
    "ErrorResponse",
    "EvidenceItem",
    "EvidencePackage",
    "Explanation",
    "FinancialMetric",
    "FinancialPeriod",
    "HealthResponse",
    "IntegrityCheck",
    "QuestionInterpretation",
    "QuestionRequest",
    "RootResponse",
    "Transaction",
    "Vendor",
]