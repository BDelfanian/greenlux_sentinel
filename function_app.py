"""Azure Functions host for the timer-triggered ETL run (infra/modules/functions.bicep;
docs/ARCHITECTURE.md#azure-service-map's "Azure Functions (Consumption, Python, timer-triggered)"
row). Thin wrapper -- see agents/etl_agent.py for the actual orchestration logic; this file's
only job is the trigger binding and logging.

Lives at the repo root (not a nested functions/ subfolder) so it sits directly alongside
`host.json` and `requirements.txt` (the latter kept for local tooling/reference only -- see its
header comment). The real deployment package is built by scripts/build_function_package.py, not
by Azure's remote (Oryx) build: live-verified in Phase 5 (docs/PROGRESS_LOG.md) that Oryx does
not reliably work for this app -- across several attempts it silently dropped a hand-vendored
greenlux_sentinel/ folder entirely, then separately wiped a pre-placed .python_packages back to
whatever requirements.txt alone produced (losing a package requirements.txt still listed). The
working approach: build a fully self-contained package locally, targeting the exact Linux
platform Azure Functions runs on, with SCM_DO_BUILD_DURING_DEPLOYMENT=false so nothing
server-side touches it -- see infra/README.md's Functions deployment section.

Schedule is a placeholder (once daily, 03:00 UTC) -- there's no documented operational cadence
requirement for this portfolio project; adjust once there's an actual answer to "how often should
this re-ingest."
"""

from __future__ import annotations

import logging

import azure.functions as func

from greenlux_sentinel.agents import etl_agent

app = func.FunctionApp()
_logger = logging.getLogger(__name__)


@app.timer_trigger(schedule="0 0 3 * * *", arg_name="timer", run_on_startup=False)
def scheduled_etl_run(timer: func.TimerRequest) -> None:
    summary = etl_agent.run_ingestion()
    _logger.info("ETL run complete: %s", summary)
