import time

from core.trace import log_event


def retry_call(
        func,
        max_attempts=3,
        base_delay=0.5,
        retryable_exceptions=(TimeoutError, ConnectionError),
        run_id=None,
        step=0
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    for attempt in range(1, max_attempts + 1):
        try:
            result = func()

            if attempt > 1:
                log_event(
                    run_id=run_id,
                    step=step,
                    event="retry_success",
                    attempt=attempt
                )

            return result

        except retryable_exceptions as e:
            log_event(
                run_id=run_id,
                step=step,
                event="retry_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=type(e).__name__
            )

            if attempt == max_attempts:
                log_event(
                    run_id=run_id,
                    step=step,
                    event="retry_exhausted",
                    attempts=max_attempts
                )
                raise

            delay = base_delay * (2 ** (attempt - 1))

            log_event(
                run_id=run_id,
                step=step,
                event="retry_wait",
                delay_ms=round(delay * 1000, 2)
            )

            time.sleep(delay)