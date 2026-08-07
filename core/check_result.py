from dataclasses import dataclass, field


@dataclass
class CheckOutcome:
    fail: dict[int, str] = field(default_factory=dict)
    review: dict[int, str] = field(default_factory=dict)
