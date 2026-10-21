from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """接口模型：Python 内用 snake_case，JSON 中用 camelCase。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
