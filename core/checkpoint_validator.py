
class InvalidCheckpointError(ValueError):
    """Checkpoint data is invalid."""


def validate_checkpoint(checkpoint, max_steps):
    """
    Validate checkpoint before resuming an Agent run.

    Returns:
        (start_step, messages)

    Raises:
        InvalidCheckpointError
    """

    if not isinstance(checkpoint, dict):
        raise InvalidCheckpointError(
            "Checkpoint must be a dictionary"
        )

    context = checkpoint.get("context")

    if not isinstance(context, dict):
        raise InvalidCheckpointError(
            "Checkpoint context must be a dictionary"
        )

    if context.get("status") != "running":
        raise InvalidCheckpointError(
            "Checkpoint status must be running"
        )

    step = checkpoint.get("step")

    if (
            type(step) is not int
            or step < 1
            or step > max_steps
    ):
        raise InvalidCheckpointError(
            "Invalid checkpoint step"
        )

    messages = context.get("messages")

    if (
            not isinstance(messages, list)
            or not messages
            or not all(
        isinstance(message, dict)
        and isinstance(message.get("role"), str)
        for message in messages
    )
    ):
        raise InvalidCheckpointError(
            "Invalid checkpoint messages"
        )

    return step, messages

