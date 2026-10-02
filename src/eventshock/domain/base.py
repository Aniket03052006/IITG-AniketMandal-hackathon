from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base for every public contract.

    ``json_schema_serialization_defaults_required`` makes the OpenAPI response schema list fields that
    have defaults as always-present, so generated client types are not riddled with ``?`` optionals.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
