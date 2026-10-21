from datetime import datetime
from typing import Any

from app.models.common import ApiModel
from app.models.survey import DisplayStatus


class InProgressItem(ApiModel):
    slug: str
    title: str
    display_status: DisplayStatus
    answered_count: int
    total_questions: int
    last_visited_at: datetime
    can_continue: bool


class SubmittedItem(ApiModel):
    response_id: str
    slug: str
    title: str
    display_status: DisplayStatus
    submitted_at: datetime


class Participations(ApiModel):
    """首页"我参与的问卷"（P22 / P23）。"""

    in_progress: list[InProgressItem]
    submitted: list[SubmittedItem]


class MyOption(ApiModel):
    text: str
    chosen: bool
    hidden: bool


class MyAnswerItem(ApiModel):
    order: int
    title: str
    type: str
    hidden: bool
    answered: bool
    options: list[MyOption] | None = None
    value: Any = None


class MyResponse(ApiModel):
    title: str
    slug: str
    submitted_at: datetime
    items: list[MyAnswerItem]
