# Member D — Baseline Measurement and Evaluation Evidence

Formal write-up of assigned work for the team final report. Evidence is drawn from the
records in `AI-log/Member-D/` (`2026-11-13_05-02-00.md`, `2026-11-23_15-25-00.md`,
`2026-11-23_16-15-00.md`, `2026-11-23_20-10-00.md`) and from the requirement registry
`docs/req/requirements.yaml`.

## 1. Role and scope

My assigned role in Section 3 of the plan is "baseline and evaluation": measure latency and
token consumption of the TradingAgents pipeline under one frozen configuration, repeat the
measurement after the team's code changes, and supply the evaluation counting rules that make
every reported number reproducible and auditable. Design decisions about the graph, the
interfaces and the CI gates belong to A, B, C and E; my contribution is the measurement
instrument, the before/after evidence, the attribution of cost to pipeline stages, and the
feasibility assessment of the cost and performance requirements.

The work addresses `REQ-TA-NFR-PERF-001`, `REQ-TA-NFR-PERF-002`, `REQ-TA-NFR-COST-001`,
`REQ-TA-NFR-COST-002`, `REQ-TA-NFR-COST-003` and `REQ-TA-NFR-EVAL-001`. All of these are
`Should` or `Could` in the registry, and all of them are stated in terms of a measured quantity
that did not exist before this work.

## 2. Method

**Frozen configuration.** Ticker NVDA, analysis date 2026-01-09, the four analysts (market,
news, social and fundamentals), one research-debate round, one risk-discussion round,
checkpoints disabled, sequential execution, provider `deepseek`, and both model tiers set to
`CS5351/DeepSeek-V4-Flash` served by the CityU shared gateway. The configuration was held
identical across the baseline cohort and the after-build cohort, so any difference between
them is attributable to the code revision and not to the model, the endpoint or the budget.
The registry requires exactly this discipline: `REQ-TA-NFR-EVAL-001` rule 6 permits a comparison
only when the run records match on `config` and `prompt_hash`, or when exactly one factor is
declared as changed.

**Measurement instrument.** Token figures were read from the token counters of a
`StatsCallbackHandler` attached directly to the graph, not from the CLI live panel. The panel
is a display surface, not an accounting surface: on the first baseline run it reported
106.2k input and 20.0k output against measured values of 114.9k and 24.1k, an undercount of
about 13% and 17% respectively. Reporting from the panel would therefore have overstated the
effect of any later change. The instrument choice is recorded in both measurement records and
is treated as part of the method, not as an implementation detail.

**Run accounting.** Only runs that reached a terminal state with a usable result entered the
cohort. Runs that stalled were counted, named and excluded, and the number excluded is reported
beside every average. This is the counting rule later written into `REQ-TA-NFR-EVAL-001`
rule 1: no run is ever removed from the completion denominator.

## 3. Before/after results

The baseline cohort was taken at revision `2c22ef9`; the after-build cohort at `98b82c9`, after
23 commits from the other members.

| Stage | Run | s | Tokens in | Tokens out | Total | Calls | Decision |
|---|---|---|---|---|---|---|---|
| Before | B1 | 117.6 | 114,911 | 24,100 | 139,011 | 16 | `Overweight` |
| Before | B2 | 110.6 | 116,314 | 22,468 | 138,782 | 17 | `Overweight` |
| After | A1 | 114.3 | 129,533 | 23,906 | 153,439 | 18 | `Hold` |
| After | A2 | 117.0 | 130,424 | 24,090 | 154,514 | 17 | `Overweight` |
| After | A3 | 111.8 | 115,820 | 21,403 | 137,223 | 17 | `Hold` |

Averages: input 115,613 → 125,259 (+8.3%), output 23,284 → 23,133 (−0.6%), total
138,897 → 148,392 (+6.8%), calls 16.5 → 17.3, wall clock 114.1 s → 114.4 s (+0.2%).
Two stalled runs were excluded and are reported as `INCOMPLETE`, not as slow completions.

The result that matters for interpretation is the shape of the change, not its size. Output
tokens and latency are flat; input tokens carry almost the whole delta. The pipeline therefore
did not become slower or more verbose in its answers, it began reading more per call: resolved
instrument context, portfolio context, expanded grounding prose in system prompts, and
structured-output schemas on bound calls. The after cohort also shows a wide spread — A3
consumed 13.7k fewer input tokens than A1 and A2 under an identical configuration — so a
single run would have supported almost any conclusion, including the wrong one. Reporting the
range and the number of excluded runs is the reason the delta can be read as a real change rather
than as noise (Henderson et al., 2018; Bouthillier et al., 2021).

Decision labels varied across identical configurations (`Overweight`, `Hold`, `Overweight`,
`Hold`) while the configuration and prompts were fixed. This is recorded as reproducibility
variance of the model, not as an effect of the code change; `REQ-TA-NFR-EVAL-001` rule 6 requires
exactly this separation, and treating label flips as a regression would have been a category
error.

## 4. Attribution

A separate diagnostic run (revision `98b82c9`, same configuration) attributed every model call
to its owning node: 16 calls, 122,324 input, 22,642 output, 144,966 total, 113.5 s. This run is
diagnostic and is excluded from the cohort averages by design.

The largest single consumer is the Market Analyst at 35,080 tokens (24.2%), followed by the
neutral risk debator (16,108), the bear researcher (14,876), the conservative debator (13,230),
the fundamentals analyst (11,128), the aggressive debator (10,376), the bull researcher
(10,367), the portfolio manager (9,191), the research manager (7,794), the news analyst (7,040),
the trader (6,981) and the sentiment analyst (2,795). Aggregated by stage, the analyst tool
loops account for 38.7%, the three risk debators for 27.4%, the researchers for 17.4%, and the
research manager, trader and portfolio manager together for 16.5%.

The mechanism behind the cost is visible inside the analyst tool loop: input per call grows
from 1,952 to 9,786 to 19,461 across successive rounds, because each round re-sends the
accumulated tool transcript to the model. Stage-level aggregation alone would have hidden this
quadratic behaviour, and the per-call trace is what allowed the team to target it.

One methodological defect surfaced here and is recorded rather than hidden: the graph labels
every react-agent call with the generic node name `agent`, so per-node attribution is only
possible by recovering the owner from the `checkpoint_ns` prefix. Any future attribution
figure produced without that recovery is unreliable.

## 5. Requirement feasibility

I assessed the cost and performance requirements against the code and answered A's two
question sets (`2026-11-23_20-10-00.md`, items D1–D12). Three conclusions changed the registry
or should change it:

1. `COST-002` (cumulative token admission) cannot be enforced in this semester's code without
   an estimation layer the run cannot defensibly provide. It was downgraded from `Must` to
   `Should` and restated as detection-only, recorded as decision D-4 in the registry entry.
2. `PERF-002` (time-budget handling) cannot meet a 2 s cancellation allowance. A cancelled
   call is not interruptible in flight — the two measured stalls each blocked for more than
   ten minutes with no timeout raised — so the allowance must describe a cooperative
   between-step check plus an explicit in-flight allowance, or the criterion is untestable.
3. `PERF-001`'s `RUN_TIME_CAP` must be fixed from measurement, as its own `open` field states.
   The observed maximum is 117.0 s with a minimum of 110.6 s across five completed runs, so a
   120 s cap has no margin and would fail on ordinary variance. A cap of 150 s with the
   measured spread recorded beside it is the defensible choice.

`COST-003` (early debate convergence) is stated in a form the current state cannot support:
only free-text `bull_history`/`bear_history` and a final rating exist, with no structured
per-round stance, so convergence cannot be detected deterministically. I recommended descoping
it rather than claiming a signal that does not exist.

## 6. Evaluation counting rules and open items

`REQ-TA-NFR-EVAL-001` defines completion rate over all runs started, quality scores over
`COMPLETED` runs only reported beside the completion rate, stop reasons for `INCOMPLETE` runs,
`N_EVAL` counting distinct cases rather than attempts, and refusal of undeclared multi-factor
comparisons. These rules exist because the naive alternative — reporting an average over
whatever runs happened to finish — silently deletes failures from the denominator, which is the
single most common defect in reported evaluation tables (Sculley et al., 2015).

Two obligations are still open and are mine, not the team's: the counting script named in the
registry's `open` field, and the rubric, critical items, evaluation profile and
`QUALITY_THRESHOLD`, which the registry assigns jointly to D and E. Until those exist, no
counting result is an acceptance result, and the registry says so explicitly.

## 7. Limitations

The measured cohort predates the current `main` (`761918e` at the time of writing). Two later
revisions matter: `aa3b02d` (perf: reduce repeated intermediate analysis context) and
`b091418` (opt-in per-run call budget, `call_cap`). The first changes exactly the quantity this
work measures — it adds the configuration key `concise_intermediate_reports`, defaulting to
`True` — so the after numbers describe `98b82c9` and must not be presented as properties of
the current tree. A run performed today with the same ticker, model and round counts is therefore
**not** the same configuration: one recorded key now differs, and under `REQ-TA-NFR-EVAL-001`
rule 6 that is a controlled change requiring the factor to be named, not a repeatability
comparison. The later `27f05f1` and `dc6f2ee` add population validation and legacy
export coverage and do not alter per-call context, so they do not invalidate the vintage
statement either way. The second change, `call_cap`, is opt-in and defaults to `None`, so it
leaves the measured cohort untouched while making any budgeted cohort non-comparable to it. The
second establishes that a formal budgeted cohort must freeze the same `call_cap` in its
evidence configuration; my cohort ran unbudgeted (`call_cap = None`), which is the correct
baseline state but is not comparable to any budgeted cohort.

Three further limits apply. Average latency, not a 20-run maximum, is what five runs can
establish, so `PERF-001` remains unproven by this evidence and is stated as a provisional
threshold. The stalled runs were observed on a different network path to the gateway than the
baseline, so their cause is recorded as infrastructure instability rather than as a code
defect, although the absence of a read timeout is a real code-level gap. Finally the attribution
run is a single run: the Pareto ordering is robust enough to direct design work, but the
individual percentages are not stable to the decimal.

**Change control.** The requirement entries cited above were read at `origin/main` `761918e`;
`docs/req/requirements.yaml` has been amended six times since the measured cohort. A quotation of
a priority, a status or a provisional threshold is therefore pinned to that revision, not to the
live file. If an entry changes again, the evidence does not become wrong — it becomes evidence
for a superseded statement, and the correct response is a dated note in the record rather than a
silent edit of the numbers.

## References

- Xiao, Y., Sun, E., Luo, D., & Wang, W. (2024). *TradingAgents: Multi-Agents LLM Financial
  Trading Framework.* arXiv:2412.20138.
- Henderson, P., Islam, R., Bachman, P., Pineau, J., Precup, D., & Meger, D. (2018). Deep
  reinforcement learning that matters. *Proceedings of AAAI-18*.
- Bouthillier, X., Delaunay, P., Bronzi, M., et al. (2021). Accounting for variance in machine
  learning benchmarks. *Proceedings of MLSys 2021*.
- Sculley, D., Holt, G., Golovin, D., et al. (2015). Hidden technical debt in machine learning
  systems. *Advances in Neural Information Processing Systems 28*.
- ACM (2020). *Artifact Review and Badging — Version 1.1.* Association for Computing Machinery.
- Team repository evidence: `kelepawuqiusi/CS5351@2c22ef9` and `@98b82c9`; requirement entries
  `REQ-TA-NFR-REPRO-001`, `PERF-001`, `PERF-002`, `COST-001`–`COST-003`, `EVAL-001` in
  `docs/req/requirements.yaml`; call-budget scope in `docs/code-governance/h1-call-budget.md`.
