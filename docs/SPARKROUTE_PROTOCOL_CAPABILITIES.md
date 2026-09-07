# Proposal: protocol as a capability, with late binding

> **Status: answered and superseded.** The gateway accepted the requirement but
> rejected the capability-string spelling, using a dedicated
> `Deployment.native_protocols` field instead — see
> `SPARKRUN_PROTOCOL_CAPABILITIES_RESPONSE.md` in the llm-gateway repo, which
> is authoritative. Their reasoning is better than the proposal's: protocol
> selects the upstream URL, headers, parser, streaming framing, error
> vocabulary and retry classification, so it is a routing dimension rather than
> an optional model feature — which makes it structurally immune to
> `capability_policy.unknown: try` rather than immune by the convention this
> document asked for. Do **not** emit `openai-chat-compatible` or
> `anthropic-messages`. Kept as the record of the argument; the singleton
> provider survived and is now named plain `sparkrun`.

Sparkrun side, 2026-08-04. For consideration alongside the settled
managed-configuration contract; nothing here blocks that work.

**Not urgent.** This is a design-for-it item, not a request. Sparkrun's use of
the gateway is much closer to a *proxy* than a *router*: the goal is one
`http://host:port/v1` exposing many models by name so nobody has to point at
individual clusters. Typically one deployment per virtual model, so weighted
pools and capability-based selection ordering mostly don't come into play. We
expect `capability_policy: {unknown: "try"}` to remain both the default and, in
practice, sufficient.

## The problem

vLLM natively serves the Responses API and Anthropic Messages at recent
versions. When it does, routing an Anthropic-shaped request straight to it is
meaningfully better than having the gateway translate — fewer moving parts, no
fidelity loss, no added latency. Today sparkrun cannot express that.

Responses is already expressible: `responses` / `responses_compact` /
`background_responses` are capabilities, so a version-aware sparkrun can simply
declare them. Anthropic is not. Protocol is carried by `Provider.Type`, which
`providerProtocol()` reads to pick the wire format, and a deployment references
exactly one provider — so every sparkrun deployment is declared
`openai_compatible` and always translated.

## Why not protocol-keyed providers

Our first thought was to drop the singleton provider for
`sparkrun:openai-compatible` + `sparkrun:anthropic`. It seemed consistent with
your rationale for rejecting per-*cluster* providers ("appropriate only if its
deployments … need distinct adapter/authentication policy" — protocol is
adapter policy).

It does not work. One vLLM instance serving both protocols natively is *one
workload*, but it would need two deployments to reference two providers —
therefore two binding revisions and two fenced activations against a single
job. Adoption by recipe fingerprint would probably make that safe, but "safe by
accident" is the wrong foundation. A deployment references one provider; it
declares many capabilities. Protocol belongs on the side that can be plural.

## The proposal

Express natively-served protocols as capabilities on the deployment:

```
openai-chat-compatible
anthropic-messages
```

alongside the existing `responses` family. Sparkrun would declare
`openai-chat-compatible` on essentially every generated deployment — that is
fine and, per the constraint below, necessary rather than redundant.

Routing then binds protocol **late**: an incoming request in protocol *P*
prefers a deployment natively declaring *P*, and otherwise falls back to the
best available translation.

Three things recommend it:

1. **It reuses machinery you already have.** Your §5.2 already orders
   deployments declaring the complete request capability set ahead of
   permissive-unknown ones. "Prefer the native protocol" largely falls out of
   that rather than needing a new selection axis.
2. **It regularizes the vocabulary.** `responses` is already an API surface
   expressed as a capability, so the capability set is half-doing this
   already; the proposal makes it consistent rather than adding a new concept.
3. **It is additive and backward compatible.** `Provider.Type` keeps its
   meaning as the provider's own protocol and auth — necessary for genuine
   third-party providers, where provider *is* protocol. Deployment capabilities
   would express *additional* natively-supported protocols. Existing documents
   are unchanged.

## Constraint: protocol capabilities must be fail-closed

Protocol capabilities must join the hard set (`files`, `responses`,
`conversations`, `single_vector_embedding`, …) and must never be subject to
`unknown: try`.

Attempting an undeclared optional feature is recoverable — the upstream returns
an error and normal retry classification applies. Attempting an undeclared
*protocol* means sending Anthropic-shaped bytes to a server that only speaks
OpenAI, which is not a graceful failure and may not even be a clean one.

This is also why sparkrun would declare `openai-chat-compatible` explicitly
even though we expect it to be universally true: the fallback decision has to
read a positive declaration rather than infer one from absence.

## Open questions for the gateway side

1. **Is there a fidelity ordering over translations?** "Best match" implies
   ranking the available translation paths when no native match exists. We
   assume translation is currently selected by provider type rather than
   ranked, so this is the part of the proposal that is genuinely new work
   rather than reuse.
2. **Naming.** The existing capability is `responses`, not `openai-responses`,
   so there is no protocol-prefix convention yet. Your call; sparkrun emits
   whatever strings you define.
3. **Should a client be able to require native, or observe that it was
   translated?** For a proxy, silently choosing the nearest match is the right
   default. A caller that cares might want a response header, or a way to
   refuse translation. Probably out of scope; raising it because "silently
   translated" is invisible today.
4. **Does `required_capabilities` on a virtual model interact usefully here?**
   A virtual model that required `anthropic-messages` would refuse to route to
   a translating deployment — which may be exactly how "require native" should
   be spelled, with no new mechanism at all.

## Sparkrun-side cost

Near zero, which is why we are comfortable designing for it now and building it
later. Protocol capabilities would be emitted by the same
`RuntimePlugin.capabilities(recipe)` hook that will produce every other
declaration — a container-tag/version check for `anthropic-messages` and the
`responses` family, and a constant for `openai-chat-compatible`. No provider
changes, no deployment-identity changes, no binding-revision changes, no effect
on the fingerprint. Just more strings in a list.
