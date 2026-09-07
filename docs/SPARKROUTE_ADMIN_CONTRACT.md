# Sparkrun ↔ llm-gateway admin API — requirements

> **Status: answered.** The gateway responded with
> `SPARKRUN_MANAGED_CONFIG_HANDOFF.md` (llm-gateway repo), which satisfies or
> exceeds REQ-1/2/3 and Q-2/3/5. Kept as the record of what sparkrun asked for
> and why. The reply, remaining gaps, and answers to the gateway's own
> questions are in `SPARKROUTE_MANAGED_CONFIG_RESPONSE.md`.

What sparkrun needs from the mutable admin API in order to manage models and
aliases on a running gateway. Written to be answered point by point: **REQ**
items are asks, **Q** items are decisions we need from the gateway side before
sparkrun can finish its half.

Context: sparkrun supervises the gateway process (acquires the pinned binary,
starts it, owns its state file) and the gateway calls back into sparkrun
through `sparkrun gateway-bridge` to activate workloads. This document is
about the *third* channel — sparkrun mutating the gateway's model surface.
The bridge protocol is unaffected by everything here.

---

## What sparkrun is trying to do

Exactly three operations, behind `sparkrun proxy alias add|rm|list`,
`sparkrun proxy sync`, and `sparkrun proxy models`:

| Sparkrun method | Needs | Frequency |
|---|---|---|
| `sync_models(endpoints, aliases)` | make the gateway serve exactly this set of discovered endpoints | every auto-discover sweep (default 30s) |
| `sync_aliases(aliases)` | apply an alias → virtual-model mapping | on user command |
| `list_models_via_api()` | read back what is served, aliases included | on user command |

`sync_models` is a **reconcile**, not an append: sparkrun computes a desired
set from live endpoint discovery and makes reality match, including deletions.
That property is what REQ-1 is about.

---

## REQ-1 — Entries must carry a source/owner tag, and sparkrun must be able to
## reconcile against only its own

The reconcile above is safe only while sparkrun is the sole writer. Once the
web UI can also create virtual models and deployments, an unscoped
"make reality match my desired set" will **delete an operator's entry on the
next 30-second sweep, silently**.

Ask: every mutable entry carries an immutable source tag (`sparkrun`,
`operator`, `ui`, …) set at creation, and list/delete operations can be scoped
to one source. Sparkrun then reads everything but only ever deletes what it
created.

This is the same asymmetry that makes the bridge's `stop` safe — sparkrun may
adopt and route to a workload a human started, but refuses to tear one down
unless its own owner tag is on it. Recommending it live in the store rather
than in sparkrun because it is the store's invariant: any second writer needs
the same protection, not just this one.

## REQ-2 — Set-at-once reconcile, or a way to emulate it safely

Sparkrun's natural call is "here is the complete sparkrun-owned set, make it
so" — one request, one transaction. If the API is per-entity CRUD instead,
sparkrun has to diff and issue N calls, and a crash midway leaves a partial
model surface.

Either a bulk/declarative endpoint scoped to a source, or documented guidance
that per-entity calls are transactional enough for this use.

## REQ-3 — Aliases addressable without re-declaring the virtual model

`sparkrun proxy alias add fast qwen` should not require sparkrun to read,
mutate and write back a whole `virtual_models` entry — that turns a one-field
change into a lost-update race with the UI.

## REQ-4 — Read-back includes aliases

`sparkrun proxy models` lists aliases alongside real models today, because
under LiteLLM an alias is an ordinary model entry. Whatever the read endpoint
is, it should return both, or clients that enumerate models will see a
regression on switching. (Related: `-list-aliases` and `GET /v1/models`.)

## REQ-5 — Loopback-friendly authentication

Sparkrun starts the gateway on the same host and holds no credential. Either
the admin surface is reachable unauthenticated on loopback, or the contract
says how sparkrun provisions itself one at first start — noting sparkrun would
then have to store that secret 0600 and manage its rotation, which is real
cost we would rather not take on for a same-host management call.

---

## Q-1 — Precedence between the config document and the DB

There are now two sources of truth. Which wins when they disagree, and does a
DB entry survive its counterpart being removed from the config document?

The shape we would expect is *file = declarative baseline, DB = runtime overlay
that wins*, but it needs stating either way: "operator edits the YAML, restarts,
nothing changes because the DB still overrides" is a confusing failure to debug.

## Q-2 — What is mutable?

Aliases only, or also virtual models / deployments / providers?

This decides how much of sparkrun's design survives. Sparkrun currently has two
modes — one where it renders the whole config document (LiteLLM parity) and one
where the operator's document is authoritative and model management is refused.
If deployments and virtual models are mutable, **the first mode retires**:
sparkrun starts the gateway on the operator's document and pushes everything it
manages over the API. That is a simplification we would take.

## Q-3 — Optimistic concurrency

Is there a compare-and-swap (against the config `Version`, or a per-entry
revision) so sparkrun's sweep cannot clobber an edit made a moment earlier in
the UI? If not, REQ-1 scoping is doing all the work and needs to be airtight.

## Q-4 — Where the SQLite file lives, and how to reset it

Sparkrun passes the gateway's other SQLite paths as flags
(`-ledger-sqlite`, `-client-credentials-sqlite`). Same treatment here, so
sparkrun can place it under its own cache dir.

`sparkrun proxy stop` currently assumes clearing the state dir is enough to
return to a clean slate. With a durable store that is no longer true — we need
either a documented file to delete or a reset operation, or `proxy` teardown
becomes quietly incomplete.

## Q-5 — Does an activatable binding become mutable too?

If `endpoint_source` bindings can be created through the admin API, sparkrun
could offer `sparkrun proxy bind <recipe>` — resolving the `recipe_revision`
fingerprint itself via the bridge's `resolve` and registering the binding, so a
user never hand-copies a 12-character digest into YAML. Not a requirement;
worth knowing whether it is on the table.

---

## Non-goals

- Sparkrun will not edit an operator-authored config document. No safe
  mechanism exists: `config.Decode` uses `DisallowUnknownFields` so sparkrun
  cannot mark the entries it owns, and round-tripping the YAML destroys
  comments and key order.
- Sparkrun will not deliver upstream credentials through this API. It holds a
  workload's API key in owner-only job metadata for health discovery only; the
  gateway resolves credentials from its own configured sources.
- None of this changes the bridge protocol. Its versioning and its strict
  response-decoding contract are covered in `SPARKROUTE_ROADMAP.md`.
