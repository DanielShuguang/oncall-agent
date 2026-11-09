"""失败归因（W4 D20）。

`error_code` 是精确原因，`category` 是看板上的一级归因：
model / tool / approval / limit / internal。新增 error_code 时同步这张表，
否则前端只能显示 "internal"。
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    APPROVAL = "approval"
    LIMIT = "limit"
    INTERNAL = "internal"


ERROR_CATEGORIES: dict[str, FailureCategory] = {
    "BUDGET_EXCEEDED": FailureCategory.MODEL,
    "MODEL_ERROR": FailureCategory.MODEL,
    "MODEL_TIMEOUT": FailureCategory.MODEL,
    "TOOL_ERROR": FailureCategory.TOOL,
    "APPROVAL_REJECTED": FailureCategory.APPROVAL,
    "APPROVAL_TIMEOUT": FailureCategory.APPROVAL,
    "STEP_LIMIT": FailureCategory.LIMIT,
    "TOOL_LIMIT": FailureCategory.LIMIT,
    "TIMEOUT": FailureCategory.LIMIT,
    "INTERNAL_ERROR": FailureCategory.INTERNAL,
    "STORE_WRITE_FAILED": FailureCategory.INTERNAL,
}


def categorize(error_code: str | None) -> FailureCategory:
    return ERROR_CATEGORIES.get(error_code or "", FailureCategory.INTERNAL)
