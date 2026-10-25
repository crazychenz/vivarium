from pydantic import BaseModel, ConfigDict


class CloudBase(BaseModel):
    """Base for generated models: accept field names as well as schema aliases."""

    model_config = ConfigDict(populate_by_name=True)
