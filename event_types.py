from dataclasses import dataclass
from typing import Optional

@dataclass
class EffectiveSpeechEvent():
    ...

@dataclass
class ViolationEvent():
    member_id: int
    hint: Optional[str]
    count: int