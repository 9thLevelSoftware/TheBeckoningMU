#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Use the project environment when present; the uv fallback is offline and lockfile-frozen.
if [[ -x ".venv/Scripts/python.exe" ]]; then
    BENCH_PYTHON=(".venv/Scripts/python.exe")
elif [[ -x ".venv/bin/python" ]]; then
    BENCH_PYTHON=(".venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
    BENCH_PYTHON=(uv run --offline --frozen python)
else
    printf '%s\n' "No project Python environment found; install dependencies or provide uv." >&2
    exit 1
fi
"${BENCH_PYTHON[@]}" - <<'PY'
import random
import time

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.settings")

import django
django.setup()

import sys
from pathlib import Path
from types import ModuleType

benchmark_package = ModuleType("dice_benchmark")
benchmark_package.__path__ = [str(Path("dice").resolve())]
sys.modules["dice_benchmark"] = benchmark_package
from dice_benchmark.dice_roller import roll_v5_pool
from dice_benchmark.roll_result import RollResult

behavior_cases = [
    ([6], [], 1, (1, True, False, False, False, "success")),
    ([10, 10], [], 4, (4, True, True, False, False, "critical_success")),
    ([10], [10], 4, (4, True, True, True, False, "messy_critical")),
    ([2], [1], 1, (0, False, False, False, True, "bestial_failure")),
    ([1], [1], 1, (0, False, False, False, False, "failure")),
]
for regular, hunger, difficulty, expected in behavior_cases:
    result = RollResult(regular, hunger, difficulty)
    actual = (
        result.total_successes,
        result.is_success,
        result.is_critical,
        result.is_messy_critical,
        result.is_bestial_failure,
        result.result_type,
    )
    if actual != expected:
        raise AssertionError(f"Dice behavior mismatch for {regular=}, {hunger=}: {actual!r}")


ITERATIONS = 30_000
random.seed(211)

successes = 0
started = time.perf_counter()
for _ in range(ITERATIONS):
    successes += roll_v5_pool(pool_size=8, hunger=3, difficulty=3).total_successes
duration = time.perf_counter() - started
if duration <= 0:
    raise RuntimeError("Benchmark timer did not advance")

print(f"METRIC v5_rolls_per_second={ITERATIONS / duration:.2f}")
print(f"METRIC v5_total_successes={successes}")
PY
