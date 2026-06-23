import sys
import asyncio

from src.nexus.runner import main, PipelineHalt

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except PipelineHalt:
        # An FSM halt that escaped a single-ticket path (the E3 batch loop catches its own).
        # _abort_with_incident already wrote the incident report + FinOps; just surface a non-zero exit.
        sys.exit(1)
