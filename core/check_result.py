from dataclasses import dataclass, field


@dataclass
class ReviewDetail:
    """A review flag with the actual values compared, so the UI can show
    the ambiguous comparison instead of just a flat reason string."""
    check: str
    message: str
    lead_value: str = ""
    candidate_value: str = ""
    candidate_context: str = ""
    score: float | None = None

    def __str__(self) -> str:
        return f"{self.check} - {self.message}"


@dataclass
class CheckOutcome:
    fail: dict[int, str] = field(default_factory=dict)
    review: dict[int, ReviewDetail] = field(default_factory=dict)
