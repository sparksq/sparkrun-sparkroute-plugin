# Model-routing review — 2026-09-08

Reviewed SparkRoute against the updated local Switchyard clone at
[`98df182c7367746d0cf09776a4e7602042469642`](https://github.com/NVIDIA-NeMo/Switchyard/tree/98df182c7367746d0cf09776a4e7602042469642).
Recommendations below are engineering judgments from the source comparison,
not claims that upstream benchmark results will transfer to our model pairs.

## What to adopt

| Upstream change or strategy | Assessment for SparkRoute |
| --- | --- |
| Stage score expressed as a probability | Keep our signed score. Upstream's closed neutral band is equivalent to `abs(score) <= threshold`; the representation is not a new routing strategy. Adopt its exact-boundary behavior so a neutral signal at threshold zero retains the configured default. |
| Codex tool-signal extraction improvements | Our adapter already supports `exec_command`, `apply_patch`, and `update_plan`. Extend it to recognize Python file-writing expressions, with a guard that prevents a search for those expressions from counting as a write. |
| Classifier plus stage routing | Best next experiment. A classifier sets the default tier at a user-turn boundary; tool signals then handle the intervening agent loop. This can address prompt difficulty that a tool-only stage router cannot observe. |
| Escalation routing | Evaluate separately for long coding tasks. It judges the weak model's completed reply and can latch a session to the strong model. Requires buffering, isolated session state, and accounting for discarded replies and judge calls. |
| Advisor gate | Evaluate as an explicit review feature. The executor keeps serving, while a stronger model reviews terminal turns and can request another attempt. This changes response delivery, not just pre-request selection. |
| Prefill classifier | Defer integration. Main now has checkpoint-backed routing, but it is feature-gated and brings encoder inference, checkpoint management, and a PyTorch device/runtime. It is not a configuration-only addition to our Go selector. |
| Routing outcome metadata | Useful direction, partly already present: SparkRoute records selected model, strategy, source, and stage signals. Expose those existing signals in the preview now; consider richer per-call attribution when adding judge calls. |

Sources: [stage scorer](https://github.com/NVIDIA-NeMo/Switchyard/blob/98df182c7367746d0cf09776a4e7602042469642/crates/libsy/src/algorithms/util/stage.rs#L419),
[Codex signal fixes](https://github.com/NVIDIA-NeMo/Switchyard/commit/1cd08bd5),
[composite routing](https://github.com/NVIDIA-NeMo/Switchyard/blob/98df182c7367746d0cf09776a4e7602042469642/docs/routing_algorithms/composite_routing.md),
[escalation routing](https://github.com/NVIDIA-NeMo/Switchyard/blob/98df182c7367746d0cf09776a4e7602042469642/docs/routing_algorithms/escalation_router_routing.md),
[advisor gate](https://github.com/NVIDIA-NeMo/Switchyard/blob/98df182c7367746d0cf09776a4e7602042469642/docs/routing_algorithms/advisor_gate_routing.md),
[prefill feature gate](https://github.com/NVIDIA-NeMo/Switchyard/blob/98df182c7367746d0cf09776a4e7602042469642/crates/switchyard-runner/src/algorithm.rs#L1093),
[outcome metadata](https://github.com/NVIDIA-NeMo/Switchyard/commit/98df182c7367746d0cf09776a4e7602042469642).

The clone also contains a plan/execute implementation on `origin/plan-execute`
(`a58f2628`), but it is **not in the reviewed main commit**. Treat it as ongoing
upstream work. The recent “restricted LLM router” change exposes an embedding
API; it does not introduce another selector strategy.

## Why stage configuration felt difficult

The existing form displayed implementation names and numerical controls before
explaining the behavior. Switching to stage routing assigned capable/efficient
roles from model-list order, without evidence that those assignments were right.
The preview accepted keyword text but no tool activity, so stage routing always
had no stage history to inspect. Weights and priorities appeared next to stage
settings even though the stage scorer does not use them. The window's label also
suggested conversational turns, while our implementation counts completed tool
results.

The sensitivity is not a measured probability that a model will succeed. With
the current scorer, one full signal has strength about `0.462`; two corroborating
signals reach about `0.762`. At the default `0.5`, investigation alone does not
escalate, and successful edits alone do not de-escalate a capable-first route.
Critical errors and compaction force the capable model; passing tests with a
recent edit and no error force the efficient model. Ordinary chat has no tool
evidence and uses the configured default. These distinctions need to be visible
before a user chooses settings.

## Changes implemented

- Group strategies by purpose and explain the metadata or observations each uses.
- Require explicit capable/efficient roles for new stage configurations.
- Provide **Cost first** / **Quality first** and **Earlier switching** /
  **More evidence** / **Strong evidence** controls. Preserve custom thresholds,
  model roles, kwargs, and all existing policy fields.
- Move numeric stage controls and policy revision into expandable sections;
  label the window as completed tool results.
- Collapse shared metadata and keyword settings, flag disabled stage roles,
  and let users reorder keyword overrides. Fix rule-name editing losing focus.
- Add named activity examples to the real native preview: no tools,
  investigation, failure recovery, productive edits, tests passed, critical
  failure, and compaction. Show the chosen role, decision source, and signal
  details. Invalidate preview results when the draft or inputs change.
- Preserve the configured default at exact threshold equality, including zero.
  Honor compaction even when prior tool events have been cleared.
- Recognize Python writes as production activity without retaining tool content.

Existing JSON configuration remains valid. The only intentional runtime changes
are the threshold-boundary fix, the compaction fix, and improved Python-write
classification. Preview examples make no upstream model calls and do not launch
workloads.

## Next experiment

Trial a user-turn classifier followed by stage routing against fixed-model and
tool-only baselines on representative local tasks. Require explicit caller-scoped
session identity, a bounded judge timeout with a defined fallback, and separate
judge usage accounting. Compare completed-task quality, total cost including
judge work, time to first token, end-to-end latency, and the frequency of
switching. Do not pick thresholds from an unrelated upstream benchmark alone.

## Verification

The full Go suite and all 101 UI tests passed. Targeted coverage includes exact
threshold boundaries, compaction without retained events, Python-write versus
search classification, stage examples, capability fallback, window behavior,
explicit role assignment, custom settings, rule ordering, and stale previews.
An isolated gateway and real Chromium browser exercised all routing examples,
changed sensitivity, validated and saved the operator configuration, and checked
desktop/mobile layouts without browser errors or horizontal overflow. No live
workload or running production gateway was changed.
The newly pinned gateway also passed both real-plugin integration tests,
including managed credentials, reconciliation, and preset persistence through
restart, plus the 18 development-gateway/version checks.
