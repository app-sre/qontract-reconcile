"""Default structlog configuration for qontract_utils.

Routes structlog through stdlib logging so it respects the root logger's level.
Callers like qontract_api override this with their own structlog.configure().
"""

import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.KeyValueRenderer(key_order=["event"]),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
)
