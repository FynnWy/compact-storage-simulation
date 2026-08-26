# Compact Storage Simulation

A discrete-event simulation of a compact, robot-operated storage system with
**top-access** retrieval — the AutoStore-style class of warehouse in which bins
are stacked in a grid and can only be taken from the top of a stack.

The simulation is the experimental apparatus for a master's thesis that
investigates four open research questions on bin reordering, bin placement and
the emergent bin distribution in such systems.

**Status: the final experiment is frozen and the campaign has been run.**
50 runs (5 policies × 10 seeds) are complete, validated and archived. See
[Results and data freeze](#results-and-data-freeze).

---

## Contents

1. [Model](#model)
2. [Policies under study](#policies-under-study)
3. [Requirements](#requirements)
4. [Setup](#setup)
5. [Running the tests](#running-the-tests)
6. [Running the simulation](#running-the-simulation)
7. [Running an experiment campaign](#running-an-experiment-campaign)
8. [Configuration](#configuration)
9. [Metrics](#metrics)
10. [Results and data freeze](#results-and-data-freeze)
11. [Project layout](#project-layout)
12. [Documentation](#documentation)

---

## Model

Bins live in vertical stacks arranged on a 2-D grid. Robots travel across the
grid, dig down to a requested target bin, carry it to a pickstation and put it
back into storage afterwards.

| Term | Meaning |
| :--- | :--- |
| **Bin** | A single tote. Has an ABC class derived from its request frequency. |
| **Stack** | A vertical pile of bins. Accessible only from the top. |
| **Grid** | The storage layout, one stack per grid cell. |
| **Blocking bin** | A bin above the target that must be relocated before the target can be picked. β denotes their number per retrieval. |
| **Request** | A demand for one bin, with an arrival time and a deadline. |
| **Robot** | Moves cell by cell, grips, relocates, retrieves and returns bins. |
| **Pickstation** | A port at the grid edge where the target bin is served. |
| **Retrieval** | One physical target bin arriving at a pickstation. The primary throughput unit. |

The engine is a genuine discrete-event simulation: it processes events at
discrete timestamps in abstract time units (ZE), not a continuous clock. Robots
plan **one action at a time** against the current warehouse state rather than
committing to a full plan up front, which is what lets several robots work in
parallel without their plans going stale.

Multi-robot coordination is handled by a `TrafficManager` with reservation
tables, deadlock detection with evade-based resolution, port-exit guards and a
move-stall recovery ladder. A `ConstraintManager` validates every action before
execution (source stack exists, bin really on top, target stack has capacity, no
two robots on the same bin, and so on).

Side-access is **not** modelled and is out of scope.

---

## Policies under study

A policy is a fixed combination of three degrees of freedom: in which order
blocking bins are put back (`reordering_strategy`), where a bin goes after
picking (`placement_strategy`), and whether blocking bins are returned to their
original stack at all (`return_blocking_bins`).

| Policy | Reordering | Placement | Return blocking bins |
| :--- | :--- | :--- | :--- |
| `baseline_reference` | LOFI | RANDOM | yes |
| `RR+RR` | LOFI | RANDOM | no |
| `LR+NR` | LOFI | NEAREST | no |
| `ABC+ABC` | ABC | ABC | yes |
| `POPULARITY+POPULARITY` | POPULARITY | POPULARITY | yes |

These five are frozen. `baseline_reference` and `RR+RR` differ in exactly one
factor and isolate the effect of the ordered return; `RR+RR` and `LR+NR` differ
in exactly one factor and isolate placement. In `ABC+ABC` and
`POPULARITY+POPULARITY` reordering and placement vary together, so those two
speak to the combined configuration effect.

Scheduling is EDF (earliest deadline first) throughout, with a fixed exogenous
deadline of `arrival + 240` ZE.

---

## Requirements

| | |
| :--- | :--- |
| **Python** | **3.10.12** — the version the final campaign was run and validated on (CPython, pyenv, local venv `.venv310`). The full test suite also passes on 3.10.12 with pytest 9.1.1. |
| **Dependencies** | `numpy`, `matplotlib`, `flask` — see `requirements.txt` |
| **Disk** | ≈ 1.4 GB free if you intend to reproduce the full campaign (raw logs are large) |

Python 3.9 also runs the code, but 3.10.12 is the reference interpreter for
anything that should be reproducible.

---

## Setup

```bash
git clone <repository-url>
cd compact-storage-simulation

python3.10 -m venv .venv310
source .venv310/bin/activate          # Windows: .venv310\Scripts\activate

pip install -r requirements.txt
pip install pytest                    # test runner, not a runtime dependency
```

---

## Running the tests

**Run the test suite before touching anything, and again before you commit.**
The simulation carries a large body of invariant and regression tests; they are
the safety net that keeps physical correctness and reproducibility intact.

```bash
python -m pytest tests/ -q
```

Expected on the reference interpreter:

```text
568 passed in ~175s (0:02:55)
```

If anything fails, stop and fix it before running experiments — a broken
invariant invalidates every run produced afterwards.

Useful subsets while working on a specific area:

```bash
# multi-robot liveness: deadlock, livelock, stall recovery
python -m pytest tests/test_deadlock.py tests/test_livelock_two_robots.py \
                 tests/test_move_stall_recovery.py -q

# physical invariants: bin uniqueness, pickup/drop legality, ordered return
python -m pytest tests/test_bin_uniqueness_validation.py \
                 tests/test_pickup_physical_invariants.py \
                 tests/test_blocker_return_invariant.py \
                 tests/test_ordered_return_stack_order.py -q

# experiment pipeline: campaign matrix, export contract, health gate, CRN
python -m pytest tests/test_campaign_matrix.py \
                 tests/test_campaign_integrity_and_preflight.py \
                 tests/test_measurement_window_export.py \
                 tests/test_rq4_export_contract.py \
                 tests/test_run_health_gate.py \
                 tests/test_reproducibility_crn.py -q
```

---

## Running the simulation

### Single run with the web visualiser

`main.py` is a small interactive smoke test — a 7 × 7 grid, 200 bins, 4 robots,
200 ZE. It is meant for looking at the mechanics, not for measurement.

```bash
python main.py
```

With `config.enable_visualization = True` (the default in `main.py`) this starts
a Flask visualiser on <http://localhost:5050>. Set it to `False` for a headless
run that prints a metrics summary and the final warehouse state instead.

### Single run in code

```python
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine

config = SimulationConfig()
config.random_seed = 42
config.simulation_time = 5000
config.enable_visualization = False

engine = SimulationEngine(config)
while engine.step() is not None:
    pass

print(engine.metrics.summary())
```

---

## Running an experiment campaign

The frozen campaign driver is `experiments/run_final_campaign.py`. It builds
each run from the frozen matrix, runs a health gate on the log, exports the CSVs
and finishes with an integrity check over the whole dataset.

**Always work through this driver, never by assembling configs by hand** — the
frozen horizons, seeds and measurement window live in
`experiments/campaign_matrix.py` and the driver is what enforces them.

```bash
# 1. Check the plan without computing anything
python -m experiments.run_final_campaign --output-dir results/my_campaign --dry-run

# 2. Short end-to-end smoke test (600 ZE, seed 42, never the final parameters)
python -m experiments.run_final_campaign --output-dir results/smoke --smoke

# 3. Hardware, disk and runtime estimate only — writes nothing
python -m experiments.run_final_campaign --output-dir results/my_campaign --estimate-runtime

# 4. The full 50-run campaign
python -m experiments.run_final_campaign --output-dir results/my_campaign
```

| Flag | Effect |
| :--- | :--- |
| `--output-dir` | Target directory (required). Refuses to write into a non-empty directory without `--resume`. |
| `--dry-run` | Validate the plan, compute nothing. |
| `--smoke` | Short end-to-end test over the same code path, with its own horizon and seed. |
| `--policy` / `--seed` | Run a subset; repeatable. Only values from the frozen matrix are accepted. |
| `--resume` | Skip runs already marked `completed` in `campaign_status.json`. |
| `--estimate-runtime` | Preflight only: hardware, free space, runtime projection. |
| `--skip-runtime-estimate` | Skip the benchmark before the start. |

The driver is deliberately **sequential** — `ExperimentWriter` appends to shared
CSV files and is not concurrency-safe. To parallelise, run disjoint subsets into
separate `--output-dir` directories and merge afterwards.

**Runtime.** The final campaign took **16.0 hours** wall time for 50 runs
(960–1471 s per run, median 1088 s) and produced ≈ 653 MiB of data. Budget
accordingly.

A campaign is only reported as successful when the closing check prints:

```text
FINAL CAMPAIGN INTEGRITY CHECK: PASS
```

Note that this gate checks structure, cross-file consistency and the hard
correctness/liveness signals (`move_recovery_unresolved`, `task_deadlock`). It
deliberately does **not** judge plausibility or performance — a slow run or an
unexpected ranking is a scientific result, not a technical failure.

---

## Configuration

All parameters live in `config/simulation_config.py`. The defaults there are a
small development setup, **not** the experiment configuration.

The frozen final configuration is assembled in
`experiments/campaign_matrix.py`:

```python
grid_width = 20            # 20 × 30 stacks, height 8 → 4800 slots
grid_depth = 30
max_stack_height = 8
bin_num = 4320             # ≈ 90 % fill level

num_robots = 8
num_pickstations = 2
pickstation_capacity = 1   # bins served simultaneously; the queue is unbounded

scheduler_strategy = "EDF"
deadline_slack = 240       # deadline = arrival + 240 ZE

request_arrival_strategy = "Poisson"
request_utilization = 0.6
bin_request_prob_strategy = "zipf"
zipf_parameter = 1.0

simulation_time = 30_000   # horizon
t_measure_start = 20_000   # measurement window [20 000, 30 000]
t_final = 30_000
```

Strategy options:

| Setting | Values |
| :--- | :--- |
| `reordering_strategy` | `LOFI`, `ABC`, `POPULARITY` |
| `placement_strategy` | `ORIGINAL`, `RANDOM`, `NEAREST`, `ABC`, `POPULARITY` |
| `return_blocking_bins` | `True` (ordered return), `False` |
| `scheduler_strategy` | `EDF`, `FIFO` |
| `bin_request_prob_strategy` | `uniform`, `zipf` |

Randomness is drawn from six named RNG streams (`initialization`, `requests`,
`service`, `relocation`, `placement`, `robots`). This is what makes **Common
Random Numbers** work: for a given seed, the request stream is identical across
all policies, so policy differences can be compared pairwise per seed.

---

## Metrics

Performance KPIs are measured **only inside the measurement window**
[20 000, 30 000] ZE, so that the system is saturated and all policies are
compared over the same interval.

**Primary**

- `bin_throughput` — physical target retrievals per time unit. One retrieval is
  counted when a target bin is physically set down at a pickstation, regardless
  of how many requests that serves.

**Secondary (service level)**

- `request_throughput`, `deadline_miss_rate`, `mean_tardiness`,
  `median_tardiness`, `p95_tardiness`, `mean_flow_time`

**Explanatory (RQ1 / RQ3)**

- `mean_blocking_bins`, `p_beta_zero`, `mean_levels_from_top`,
  `share_retrievals_top20pct`, `mean_dig_duration`, `mean_batch_size`,
  `pickstation_utilisation_mean`, `retrievals_ps0` / `retrievals_ps1`

**Spatial convergence (RQ4)**

- `rq4_status`, `rq4_convergence_time_ZE`, `rq4_convergence_retrievals`,
  `rq4_plateau_level`, `rq4_redivergence`, `rq4_blocks` — computed offline from
  the full time series starting at t = 0, independent of the measurement window.

The seed is the statistical replication unit (n = 10 per policy, paired via
CRN). Individual requests or retrievals are **not** independent replications;
pooled raw rows are for descriptive histograms only.

Under the chosen load the request queue is deliberately unstable, so tardiness
measures **backlog age rather than service quality** and is interpretable only
as a paired policy comparison.

---

## Results and data freeze

The final campaign lives under `results/` and is **frozen**. Neither
`results/final/` nor `results/final_raw/` may be modified.

```text
results/
├── final/                          # raw campaign data (57 files, ≈ 653 MiB)
│   ├── runs.csv                    # one row per run, 52 columns
│   ├── retrievals.csv              # one row per physical retrieval
│   ├── requests.csv                # one row per served request
│   ├── distribution.csv            # spatial snapshots for RQ3 / RQ4
│   ├── run_meta.json               # config, RNG streams, full RQ4 analysis
│   ├── campaign_status.json        # per-run status
│   └── logs/<run_id>.log           # 50 run logs
├── final_raw/                      # byte-identical archival copy, read-only
├── FINAL_DATA_SHA256.txt           # SHA-256 manifest over results/final/
├── FINAL_DATA_FREEZE.md            # freeze record (commit, interpreter, status)
└── FINAL_DATA_VALIDITY_AUDIT.md    # data / log / trajectory validity audit
```

Both raw directories are excluded from version control; the manifest is not, so
any later change to either tree remains provable:

```bash
cd results/final && sha256sum -c ../FINAL_DATA_SHA256.txt
```

Campaign and audit status:

```text
50/50 runs, FINAL CAMPAIGN INTEGRITY CHECK = PASS
FINAL_DATA_VALIDATED          = YES
READY_FOR_SCIENTIFIC_ANALYSIS = YES
```

Two known data notes, documented in the audit:

- **F-1** — `POPULARITY+POPULARITY/seed1` contains a `request_id` labelling
  defect outside the measurement window. Do not treat `request_id` as a unique
  key within a run.
- **F-2** — `baseline_reference/seed99` technically ends at `t_end = 30003`.
  Measurement window and KPIs are unaffected.

All future analysis artefacts belong in a **separate** analysis directory and
must never write back into either raw directory.

---

## Project layout

```text
compact-storage-simulation
├── config/              # SimulationConfig, init strategies, RNG streams
├── docs/                # audits, freeze documents, experiment readiness
├── events/              # event definitions and types
├── experiments/         # campaign matrix, runner, export, health gate
├── logging/             # event logging
├── metrics/             # metric collection, RQ4 plateau rule
├── requests_/           # request generation and queues
├── results/             # frozen campaign data and freeze/audit documents
├── simulation/          # engine, event handler, scheduler, robot tasks
├── state/               # grid, stacks, bins, robots, pickstations
├── static/, templates/  # web visualiser assets
├── strategies/          # top-access strategy, reordering, placement, relocation
├── tests/               # 568 tests
├── traffic/             # pathfinding, reservations, deadlock detection, ports
├── utils/               # helpers and visualisation
├── main.py              # interactive single-run entry point
├── run_experiments.py   # legacy experiment script — see note below
└── requirements.txt
```

`run_experiments.py` is superseded by `experiments/run_final_campaign.py` and
writes legacy outputs to `results/legacy/`. It predates the frozen campaign
driver and knows nothing about the frozen run matrix, the frozen horizons or the
integrity check. **For reproducible and final experiments, use
`experiments/run_final_campaign.py` exclusively.**

---

## Documentation

| Document | Contents |
| :--- | :--- |
| [`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) | Layer-by-layer walkthrough of the codebase |
| [`docs/SCIENTIFIC_EXPERIMENT_READINESS.md`](docs/SCIENTIFIC_EXPERIMENT_READINESS.md) | The four research questions verbatim, plus their mapping onto this model |
| [`docs/FINAL_EXPERIMENT_FREEZE_2026-08-21.md`](docs/FINAL_EXPERIMENT_FREEZE_2026-08-21.md) | Frozen methodology: KPI definitions, statistics, RQ4 rule, limitations |
| [`docs/Pickstation_Logik.md`](docs/Pickstation_Logik.md) | Binding rules for ports and the buffer zone |
| [`docs/SIMULATION_CONSISTENCY_AUDIT_2026-08-20.md`](docs/SIMULATION_CONSISTENCY_AUDIT_2026-08-20.md) | Consistency audit of the simulation core |
| [`docs/STRATEGY_CORRECTNESS_AUDIT_2026-08-21.md`](docs/STRATEGY_CORRECTNESS_AUDIT_2026-08-21.md) | Correctness audit of the strategy implementations |
| [`docs/REPRODUCIBILITY_AUDIT_2026-08-21.md`](docs/REPRODUCIBILITY_AUDIT_2026-08-21.md) | Reproducibility and CRN audit |
| [`docs/FIX_IMPLEMENTIERUNG_2026-08-19.md`](docs/FIX_IMPLEMENTIERUNG_2026-08-19.md) | Technical handover of the 2026-08-19 fixes |
| [`docs/Testfehler_Zusammenfassung.md`](docs/Testfehler_Zusammenfassung.md) | History of resolved failure groups |
| [`experiments/experiment_setup.md`](experiments/experiment_setup.md) | Derivation of the experiment parameters |

Most documents are in German; the code and this README are in English.

---

> This project serves the scientific investigation of warehouse logistics
> algorithms as part of a master's thesis at the University of Hamburg
> (Institute of Operations Management).
