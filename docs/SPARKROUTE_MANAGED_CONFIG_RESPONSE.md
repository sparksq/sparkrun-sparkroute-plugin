# Response to `SPARKRUN_MANAGED_CONFIG_HANDOFF.md`

> **Status: closed.** All seven CRs were resolved in the gateway's
> `SPARKRUN_MANAGED_CONFIG_RESPONSE.md`, which is authoritative where it and the
> handoff differ. Two proposals in §3 below were **corrected there and are
> superseded** — see the corrections note under §3.3 and CR-5. One further gap
> found while reading it (generated deployment names can collide) is tracked in
> §6 at the end of this document.

Sparkrun side, 2026-08-04. Replies to the handoff dated the same day.

Verdict: the seam is right and we accept it. Two-owner sets with an
exclusive-writer role, whole-set atomic replacement, and
`expected_active_revision` CAS answer our requirements more completely than we
asked — the set isolation is stronger than the per-entity source tag we
proposed, and CAS was an open question we expected to argue about.

Current local-operation behavior: with no explicit admin address, SparkRoute's
admin/API/UI routes share the data listener. Admin auth **defaults to open** —
a local single-user install reaches its console on the machine and port already
serving inference without a second setup step. SparkRoute always starts this
profile in `token-file` admin mode: a missing file is open; atomic creation or
replacement requires the new bearer immediately; removal opens it immediately.
No listener restart is involved.

That exposure is announced rather than prevented: `proxy start` (including
`--dry-run`) emits a danger banner naming both remedies, and `proxy ui` repeats
it. `sparkrun proxy admin-token set|get|clear` owns the live token and its
restart-compatible config field. A supplied proxy master key protects the data
listener through a separate private token file and seeds admin auth if no
independently rotated token exists. Public token-file listeners always receive
`-allow-insecure-admin-nonloopback` because the token may be cleared while the
process remains up; the danger banner appears only when it is actually absent.

Below: what we accept as-is, seven change requests, and answers to your section
10 questions.

---

## 1. Accepted as-is

| Our ask (`SPARKROUTE_ADMIN_CONTRACT.md`) | Handoff | Note |
|---|---|---|
| REQ-1 source/owner tag, scoped reconcile | §2 | Exceeded. Set-level isolation with role separation beats per-entity tagging: sparkrun *cannot* delete operator content, rather than merely declining to. |
| REQ-2 set-at-once reconcile | §4.4 | Exactly this. |
| REQ-3 alias mutation without lost-update | §4.4 + 409 | Satisfied differently and acceptably. Whole-set PUT is read-modify-write, but the sparkrun set has exactly one writer, so the race we were guarding against cannot occur; CAS covers the merged document. |
| Q-2 what is mutable | §2 | Providers, deployments, virtual models. **Our managed-config-file mode retires** — see §4. |
| Q-3 optimistic concurrency | §4.3/4.4 | `expected_active_revision` + 409 with re-read. |
| Q-5 activatable bindings mutable | §8 | Yes. Enables `sparkrun proxy bind <recipe>` resolving the fingerprint itself, so nobody hand-copies a 12-character digest. |

We also accept: no JSON Patch, no per-entity append, no SIGHUP, no operator-set
access, no shared-write to the SQLite file. Those match our stated non-goals.

---

## 2. Change requests

### CR-1 — The reconciler cannot read what the gateway actually serves

§3: the narrow role "cannot read the operator document, merged document, global
history". But `sparkrun proxy models` is an existing user-facing command that
lists everything the gateway serves — under LiteLLM it returns the whole model
list, aliases included. With only `config_reconcile:sparkrun` we can report our
own set and nothing else, which is a visible regression on switching.

Ask, in preference order:

1. `status_read` is documented as including served virtual-model and alias
   **names** (no config detail), and we grant sparkrun that role too. This is
   the cheapest path and also answers your question 4 — see §3.4.
2. Failing that, a content-free merged name list on the collection endpoint:
   `GET /v1/config/managed-sets?include=served_names`, returning names and
   owners only.

We do not need operator configuration content — only the names, so a user
asking "what can I call?" gets a complete answer.

### CR-2 — Conflict errors must name the conflicting entity and its owner

§2: duplicate provider/deployment/virtual-model/**alias** names fail. Combined
with CR-1's read restriction, `sparkrun proxy alias add fast qwen` against an
operator set that already defines `fast` produces a 400
`invalid_configuration` that sparkrun cannot explain, because it cannot see the
operator set to discover why.

Ask: the bounded validation message for a duplicate-name rejection identifies
the offending name and the owning set (`alias "fast" already defined by owner
"operator"`). Names only — no surrounding configuration. Without this the
user-facing error is "the gateway rejected this" with no remedy.

The same applies to §2's cross-owner reference case: if an operator virtual
model references a generated deployment and blocks its deletion, we need the
referencing entity named or we cannot tell the user what to unpick.

### CR-3 — Document the `file` → `sqlite` migration for existing operator content

§1 presents `file` and `sqlite` as alternative source modes. Sparkrun already
ships a mode where `proxy.gateway_config` names an operator-authored YAML and
we pass `-config`. Two things are unstated:

- Is `-config` ignored in `sqlite` mode, or still loaded as a third input?
- How does an operator's existing document become the `operator` managed set?

We would like a documented import — something like
`llm-gateway config import -config gateway.yaml -config-sqlite state/config.db
-owner operator` — so switching modes is not "retype your routing policy into
the UI". If the answer is "operator authoring moves to the API/UI, no import",
say so explicitly and we will surface that as a one-way migration in
`sparkrun proxy` docs.

### CR-4 — Confirm `capabilities` may be omitted, and document the baseline

§8 requires capabilities to "describe what the served model actually supports".
**Sparkrun cannot infer this.** A recipe declares model, runtime, container and
serve arguments; nothing in it says whether the served model does tools, vision,
or embeddings. We are not willing to guess, because a wrong capability claim
fails a request *after* it is admitted.

Ask: confirm `capabilities` may be omitted for baseline text chat completions
(the `omitempty` in the struct suggests yes), and document what the empty set
admits. Sparkrun will then add an explicit optional recipe field for operators
to declare capabilities, and emit only what is declared.

This matters most for your acceptance scenario 10: routing `/v1/embeddings`
requires `single_vector_embedding`, so **that scenario cannot pass until
sparkrun recipes can declare it**. We will add the recipe field; flagging it so
the harness is not blocked on a mystery.

### CR-5 — Agree the derivation and stability contract for `endpoint_source.revision`

§8 shows `revision: "stable-binding-revision"` alongside `recipe_revision`.
`recipe_revision` is ours and well-defined (`derive_recipe_fingerprint`, a
12-char digest of the declared serve configuration). The separate binding
`revision` is not.

~~We propose sparkrun derives it as a digest over the binding's own inputs —
`recipe_revision`, `cluster_candidates`, `overrides`, and the virtual-model
name~~ — **superseded**: the virtual-model name must be excluded. Several
virtual models may route to one deployment, and a client-facing rename must not
change workload identity. The agreed derivation is in the gateway response §6
(SHA-256 over canonical JSON of `version`/`controller`/`deployment`/`recipe`/
`recipe_revision`/`cluster_candidates`/`overrides`, first 12 hex chars).

Answered: a binding-revision change forces revalidation and re-admission, not a
workload restart. The gateway does not proactively stop a running workload; the
next request takes a fresh fenced activation, and the bridge may adopt the
running job when its recipe revision still matches.

### CR-6 — Reset and teardown

`sparkrun proxy stop` currently returns to a clean slate by clearing its state
dir. With a durable config DB that is no longer true. We need either "deleting
the `-config-sqlite` file is supported and sufficient" stated plainly, or a
reset operation. Otherwise `sparkrun proxy` teardown is quietly incomplete and
a later start inherits stale generated entities.

Relatedly: is it safe to delete the config DB while the gateway is stopped, or
does the credentials DB need clearing in step with it?

### CR-7 — Confirm credential minting works before first gateway start

**Current OSS note (2026-08-16):** this bootstrap sequence is retained
below as protocol history, but Sparkrun's OSS profile no longer uses it.
Reconciliation and the UI share the live admin token file described above, so
normal startup needs neither `-client-credentials-sqlite` nor an offline
credential subprocess. The enterprise profile's separate listeners and
credential requirements are unchanged.

§3 requires `-client-credentials-sqlite` and a pre-provisioned key, but the
gateway refuses `sqlite` mode without one — so the credential must exist before
the first start. We read `llm-gateway client-credentials create -database …` as
an offline CLI operating directly on the file. Please confirm, since our
bootstrap sequence depends on it:

1. sparkrun creates the state dir 0700 and both DB paths;
2. sparkrun runs `client-credentials create`, captures the secret from stdout;
3. sparkrun stores it 0600 in its own state dir;
4. sparkrun starts the gateway;
5. sparkrun reconciles.

---

## 3. Answers to your section 10 questions

**3.1 — Authoritative sparkrun catalog object.**
The **recipe** is authoritative. `recipe` = qualified name (`@registry/name`);
`recipe_revision` = `derive_recipe_fingerprint(recipe, overrides)`, a digest of
the *declared* serve configuration, deliberately host-independent so it is
reproducible without probing hardware. Provider `type` is always
`openai_compatible` — every sparkrun runtime (vLLM, SGLang, llama.cpp, TRT-LLM)
serves an OpenAI-compatible HTTP API. Upstream `model` is the recipe's
`served_model_name` default, falling back to `model`. Aliases come from
`aliases:` in `proxy.yaml`, which is sparkrun's existing user-facing surface.
Capabilities: no source today — see CR-4.

**3.2 — Self-contained generated sets.**
Yes. Sparkrun emits a self-contained fragment: generated deployments reference
generated providers, generated virtual models reference generated deployments.
We will not depend on cross-owner references. If an operator references a
generated deployment and blocks its removal, we surface the gateway's error
rather than working around it — contingent on CR-2 naming the referrer. We do
not want a tombstone policy for this; see 3.7.

**3.3 — Naming and ordering.**

| Entity | Name | Rationale |
|---|---|---|
| provider | ~~`sparkrun:<cluster>`~~ → `sparkrun` | **Superseded.** A provider is protocol/auth configuration, not cluster identity: one deployment references one provider, but an activatable binding lists *several* `cluster_candidates`, so per-cluster providers cannot express a multi-candidate deployment. The plain singleton identity does not imply one wire protocol; `native_protocols` declares those. |
| deployment | `sparkrun:<recipe_revision>` | Already an immutable content digest; changes exactly when the served configuration does. |
| virtual model | the served model name, **unprefixed** | User-facing — clients call it. Prefixing would make every model name ugly to buy collision avoidance we would rather detect (CR-2). |

Ordering: every generated list sorted by `name`; pool targets sorted by
deployment name; aliases sorted. Nothing derived from discovery iteration order,
so a reconcile is byte-stable when the catalog is unchanged.

**3.4 — Serving-revision check.**
`status_read` as an additional role is acceptable and preferred — we already
supervise the process, so granting ourselves a second role costs nothing, and it
keeps the managed-set response narrow. This is the same grant CR-1 asks for, so
please treat them together: one extra role solving both.

**3.5 — Bearer secret provisioning and rotation.**
Sparkrun mints it (CR-7 sequence) and stores it 0600 in its proxy state dir
beside `state.yaml`, which already holds secrets under a 0700 directory. Never
in argv, never in a generated document, never logged. Rotation: sparkrun
re-mints and replaces the stored secret on request; we will expose that as an
explicit command rather than doing it automatically, since a failed rotation
should not silently stop reconciliation.

**3.6 — Reconciliation triggers and interval (implemented correction).**
Immediate on: gateway start, successful `sparkrun proxy load` / `unload`,
`sparkrun proxy alias` commands, and explicit `sparkrun proxy sync` (also
available as `proxy models --refresh`). Periodic endpoint discovery is disabled
for SparkRoute: the activatable binding catalog is durable desired state, so a
periodic liveness sweep must not remove a cold route. CAS conflicts retry with
bounded backoff. An unchanged desired set creates no revision or activation.

**3.7 — Recipe deletion.**
Remove immediately, no tombstone. A tombstone is state sparkrun would then have
to own, expire and reconcile, and the catalog is already our desired state — a
deleted recipe is a deliberate act. If client-facing stability turns out to
matter we would rather add an explicit "pinned" concept in `proxy.yaml`, where
the user can see it, than infer retention from a deletion.

---

## 4. What changes on the sparkrun side

For your planning; no action required from you.

- **Our managed-config-file mode retires.** Sparkrun currently renders a whole
  gateway document to disk when no operator config is set (LiteLLM parity).
  That is superseded: in `sqlite` mode we own the `sparkrun` set through the
  API and write no gateway file at all.
- **Roadmap items 1–3 are dropped** (repeatable `-config` merge, SIGHUP/watch
  reload, models view on the health listener). Your §7 runtime application
  supersedes the reload item outright, including the concern we raised about
  activation leases surviving a config change.
- **Desired state moves from discovery to catalog.** Our reconcile input
  becomes the recipe catalog, not the set of currently-live endpoints. Worth
  stating because it removes a deadlock we would otherwise have walked into:
  generating deployments from live discovery means a workload going down
  deletes its own deployment, after which the gateway can never activate it
  again. Please confirm you expect activatable-from-catalog as the primary
  shape, and tell us whether `discovered` endpoint sources still have a role
  (e.g. for workloads a user launched outside the catalog).
- **`discovered` sources retain a bounded explicit role.** Startup discovery
  and `sparkrun proxy sync` persist a separate `discovered_models:` snapshot
  for healthy workloads launched outside `proxy load`. Those entries render
  as warm-only `endpoint_source.type: discovered` deployments. A later
  explicit sync replaces only that snapshot; it never edits `bindings:`.
  Models already represented by an activatable binding are excluded, and a
  later `proxy load` promotes/removes an existing warm-only import so it cannot
  reappear after unload.
- **Two roadmap items survive unchanged**: bridge protocol version negotiation,
  and the strict-decoding wire contract on bridge *responses*
  (`DisallowUnknownFields` in `pkg/sparkrun/bridge.go` makes each result's key
  set a hard contract). Neither is touched by this seam.

---

## 5. Blocking vs non-blocking

**Blocking for a working integration:** CR-4 (capabilities baseline) and CR-7
(offline credential minting) — we cannot generate a valid document or bootstrap
without them. CR-5 needs an answer before we can emit activatable bindings at
all.

**Blocking for acceptance scenario 10** (embeddings): CR-4 plus the sparkrun
recipe field it implies.

**Not blocking, but user-visible if unresolved:** CR-1 (`proxy models`
regression), CR-2 (unexplainable alias conflicts), CR-3 (migration),
CR-6 (incomplete teardown).

---

## 6. Follow-up: generated deployment names can collide

Found while implementing against the agreed contract; not covered by either
document.

The agreed deployment identity is `sparkrun:<recipe_revision>`, but the binding
digest (gateway response §6) includes `recipe` — the qualified name — as a
distinct input. Those two disagree about what identifies a deployment, and the
gap is reachable.

`derive_recipe_fingerprint` digests the *declared serve configuration* and
deliberately excludes the recipe's name and registry. So the same recipe present
in two registries — a local copy of a community recipe, which is a normal thing
for users to have — yields **one** `recipe_revision` and therefore one
deployment name, but **two** binding revisions, because `recipe` differs. A
catalog projection would emit two deployments with the same name and be rejected
with `400 invalid_configuration`, on the user's ordinary catalog.

Sparkrun will resolve it on its side by **deduplicating the projection by
`recipe_revision`**, emitting one deployment per distinct fingerprint and using
the lexically-first qualified name as `recipe` in both the binding digest and
`endpoint_source.recipe`. That is consistent with sparkrun's existing semantics:
two recipes with identical serve configuration already share an `intent_id`, so
`sparkrun run` on either adopts the same container — they are the same workload,
and collapsing them is correct rather than a workaround.

No gateway change requested. Raising it because the representative-name choice
is observable to you: `endpoint_source.recipe` may name a different registry
than the one a user typed, and `EnsureReady` will resolve that name. Say so if
you would rather the deployment name carry a recipe-name component instead, so
the two stay distinct entities.
