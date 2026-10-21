from typing import Any

from app.models.common import ApiModel


class OptionStat(ApiModel):
    option_id: str
    text: str
    hidden: bool
    count: int
    ratio: float  # 选择该项的人数 / 本题回答人数


class QuestionStat(ApiModel):
    question_id: str
    order: int
    type: str
    title: str
    hidden: bool
    answered_count: int
    skipped_count: int  # 答卷总数 - 本题回答人数（被跳转跳过或选填未答）
    options: list[OptionStat] | None = None  # 单选 / 多选
    average: float | None = None             # 数字
    min: float | None = None
    max: float | None = None
    values: list[Any] | None = None          # 文本 / 数字的全部回答


class SurveyStats(ApiModel):
    survey_id: str
    title: str
    total_responses: int
    questions: list[QuestionStat]
