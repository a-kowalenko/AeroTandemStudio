from dataclasses import dataclass
from typing import Dict


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    all_scores: Dict[str, float]
