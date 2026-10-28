"""Synchronous HTTP API for the Tiny Agent Harness V1.0 runtime."""

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from core.loop import run
from core.memory import MemoryManager
from core.trace import create_run_id


RUN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"


class StartRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=16000)
    max_steps: int = Field(default=5, ge=1, le=100)
    run_id: Optional[str] = Field(default=None, pattern=RUN_ID_PATTERN)

    @field_validator("task")
    @classmethod
    def task_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task must not be blank")
        return value


class ResumeRunRequest(BaseModel):
    max_steps: int = Field(default=5, ge=1, le=100)


class RunResponse(BaseModel):
    run_id: str
    status: str
    result: Optional[str] = None
    checkpoint: Optional[Dict[str, Any]] = None


app = FastAPI(
    title="Tiny Agent Harness",
    version="1.0.0",
    description=(
        "A small, recoverable agent loop with checkpointing and durable "
        "tool-call idempotency."
    ),
)


def _get_checkpoint_or_service_error(run_id: str):
    try:
        return MemoryManager().get_checkpoint(run_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Checkpoint storage unavailable: {type(error).__name__}",
        ) from error


def _status_for(result: Optional[str], checkpoint) -> str:
    checkpoint_status = None
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("context"), dict):
        checkpoint_status = checkpoint["context"].get("status")

    if checkpoint_status == "completed":
        return "completed"
    if checkpoint_status == "needs_manual_reconciliation":
        return "needs_manual_reconciliation"
    if result and result.startswith("Agent failed:"):
        return "failed"
    if result and result.startswith("Agent stopped:"):
        return "stopped"
    if checkpoint_status == "running":
        return "running"
    return "unknown"


def _response(run_id: str, result: Optional[str], checkpoint) -> RunResponse:
    return RunResponse(
        run_id=run_id,
        status=_status_for(result, checkpoint),
        result=result,
        checkpoint=checkpoint,
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/runs", response_model=RunResponse)
def start_run(request: StartRunRequest) -> RunResponse:
    run_id = request.run_id or create_run_id()

    if request.run_id is not None:
        existing = _get_checkpoint_or_service_error(run_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="run_id already has a checkpoint; use the resume endpoint",
            )

    result = run(
        task=request.task,
        max_steps=request.max_steps,
        run_id=run_id,
        resume=False,
    )
    checkpoint = _get_checkpoint_or_service_error(run_id)
    return _response(run_id, result, checkpoint)


@app.post("/runs/{run_id}/resume", response_model=RunResponse)
def resume_run(run_id: str, request: ResumeRunRequest) -> RunResponse:
    try:
        result = run(
            task="Resume the existing agent run.",
            max_steps=request.max_steps,
            run_id=run_id,
            resume=True,
        )
    except ValueError as error:
        message = str(error)
        response_status = (
            status.HTTP_404_NOT_FOUND
            if message.startswith("Checkpoint not found:")
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=response_status, detail=message) from error

    checkpoint = _get_checkpoint_or_service_error(run_id)
    return _response(run_id, result, checkpoint)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    checkpoint = _get_checkpoint_or_service_error(run_id)
    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    return _response(run_id, None, checkpoint)
