from jsonschema import validate
from jsonschema.exceptions import ValidationError


def validate_arguments(arguments: dict, schema: dict):
    try:
        validate(instance=arguments, schema=schema)
        return True, None
    except ValidationError as e:
        return False, e.message