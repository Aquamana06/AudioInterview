"""Interview diagnostics displayed in the server terminal."""

import json
import logging
import sys


logger = logging.getLogger("audiointerview")


def configure_logging() -> None:
    # Own the application handler so Uvicorn's root logger settings cannot hide INFO.
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, session_id: str, **details) -> None:
    logger.info("[interview] %s", json.dumps(
        {"event": event, "session_id": session_id, **details}, ensure_ascii=False,
    ))


def log_turn(session_id: str, result: dict, *, replay: bool = False,
             depth_stagnation_count: int | None = None) -> None:
    log_event(
        "turn_completed", session_id, replay=replay,
        turn=result["state"].get("turn_count", 0), stateLabel=result["stateLabel"],
        state=result["state"], extracted=result.get("extracted"),
        profileExtraction=result.get("profileExtraction"), guide=result.get("guide"),
        depth_stagnation_count=depth_stagnation_count, response=result["text"],
    )
