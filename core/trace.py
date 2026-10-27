import json
import logging
import time
import uuid


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("tiny_agent_harness")


def create_run_id():
    return uuid.uuid4().hex


def log_event(run_id, step, event, **kwargs):
    data = {
        "run_id": run_id,
        "step": step,
        "event": event,
        "timestamp": time.time(),
        **kwargs
    }

    logger.info(json.dumps(data, ensure_ascii=False))