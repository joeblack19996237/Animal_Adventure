from __future__ import annotations

from enum import Enum, auto


class HarnessState(Enum):
    INIT = auto()
    PARSING = auto()
    TASK_BUILD = auto()
    EXECUTING = auto()
    REVIEWING = auto()
    FIXING = auto()
    REGRESSION_TESTING = auto()
    NEXT_PHASE = auto()
    CLEANUP = auto()
    EVALUATING = auto()
    COMPLETE = auto()
    HALTED = auto()
