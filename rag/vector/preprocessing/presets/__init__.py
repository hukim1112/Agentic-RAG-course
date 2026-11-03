"""문서 계열별 정규화 설정 및 메타데이터 프리셋 (AWS Well-Architected 등)"""

from rag.vector.preprocessing.presets.aws_waf import AWS_PDF_OPTIONS, aws_metadata
from rag.vector.preprocessing.presets.bok import BOK_PDF_OPTIONS, bok_metadata

__all__ = [
    "AWS_PDF_OPTIONS",
    "aws_metadata",
    "BOK_PDF_OPTIONS",
    "bok_metadata",
]
