# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Publish discovered deployments even when their default public name is taken."""

from copy import deepcopy


def prepare_discovery_routes(document: dict, context: dict) -> tuple[dict, tuple[str, ...]]:
    """Filter optional discovery routes; explicit bindings still validate strictly.

    Context is a single revision-bound gateway snapshot. It contains the current
    owned document, public claims from other owners, and references into our set.
    Never copy or edit the operator's configuration.
    """
    document = deepcopy(document)
    claims = {claim["name"]: claim for claim in context["reserved_names"]}
    referenced = set(context["referenced_deployments"])
    deployments = {item["name"]: item for item in document["deployments"]}
    for previous in context["document"].get("deployments", []):
        if (
            previous["name"] in referenced
            and previous["name"] not in deployments
            and previous.get("endpoint_source", {}).get("type") == "discovered"
        ):
            # A saved operator route is a durable reference. Retain its target
            # offline until the operator removes that reference.
            deployments[previous["name"]] = deepcopy(previous)
    document["deployments"] = sorted(deployments.values(), key=lambda item: item["name"])
    discovered = {name for name, item in deployments.items() if item.get("endpoint_source", {}).get("type") == "discovered"}
    models = {item["name"]: item for item in document["virtual_models"]}
    retained_models = set(context.get("referenced_models", []))
    for previous in context["document"].get("virtual_models", []):
        if previous["name"] in retained_models and previous["name"] not in models:
            models[previous["name"]] = deepcopy(previous)
    optional = set()
    targets = {}
    for name, model in models.items():
        ids = {target["deployment"] for pool in model.get("pools", []) for target in pool["targets"]}
        targets[name] = ids
        if ids and ids <= discovered:
            optional.add(name)
    for name, model in models.items():
        parent = model.get("profile", {}).get("parent")
        if parent in optional:
            optional.add(name)
            targets[name] = targets[parent]

    warnings = []
    removed = set()

    def conflict(public_name, name):
        claim = claims[public_name]
        warnings.append(
            'Discovered model "%s": public name "%s" is reserved by %s route "%s"; '
            "the deployment is available in the route editor." % (name, public_name, claim["owner"], claim["model"])
        )

    for name in sorted(optional):
        model = models[name]
        parent = model.get("profile", {}).get("parent")
        # Profile aliases are inherited by the gateway. A colliding inherited
        # alias cannot be removed from the child alone, so withhold that optional
        # profile while retaining the base route and deployment.
        inherited_conflicts = []
        if parent and name.startswith(parent + ":"):
            suffix = name[len(parent) :]
            inherited_conflicts = [alias + suffix for alias in models[parent].get("aliases", []) if alias + suffix in claims]
        if inherited_conflicts:
            removed.add(name)
            for public_name in inherited_conflicts:
                conflict(public_name, name)
        elif name in claims:
            removed.add(name)
            # A user already attached every target to an operator route: this
            # is a completed correction, not a recurring discovery warning.
            if targets[name] - referenced:
                conflict(name, name)
        else:
            aliases = model.get("aliases", [])
            for alias in aliases:
                if alias in claims:
                    conflict(alias, name)
            if aliases:
                model["aliases"] = [alias for alias in aliases if alias not in claims]
    document["virtual_models"] = [
        model for name, model in sorted(models.items()) if name not in removed and model.get("profile", {}).get("parent") not in removed
    ]
    return document, tuple(warnings)


def retain_recipe_bindings(document: dict, previous: dict) -> dict:
    """Keep saved pins and IDs until the gateway safely applies recipe updates.

    Recipe/placement/override changes are explicit binding edits. Catalog drift
    alone must not race gateway admission or reset an operator reference into
    this set. The gateway applies both owners' updates under workload gates.
    """

    def key(deployment):
        source = deployment.get("endpoint_source", {})
        if source.get("type") != "activatable" or source.get("controller") != "sparkrun":
            return None
        return (source.get("recipe"), tuple(source.get("cluster_candidates", [])), tuple(sorted(source.get("overrides", {}).items())))

    saved = {key(item): item for item in previous.get("deployments", []) if key(item) is not None}
    document = deepcopy(document)
    names = {}
    for index, item in enumerate(document.get("deployments", [])):
        old = saved.get(key(item))
        if old is None:
            continue
        names[item["name"]] = old["name"]
        if item["endpoint_source"].get("recipe_revision") != old["endpoint_source"].get("recipe_revision"):
            document["deployments"][index] = deepcopy(old)
        else:
            item["name"] = old["name"]
            item["endpoint_source"] = deepcopy(old["endpoint_source"])
    for model in document.get("virtual_models", []):
        for pool in model.get("pools", []):
            for target in pool.get("targets", []):
                target["deployment"] = names.get(target["deployment"], target["deployment"])
    # Profiles newly introduced by an unapplied recipe cannot be advertised yet.
    implementations = {item["name"]: item.get("request_profiles", {}) for item in document.get("deployments", [])}
    models = {item["name"]: item for item in document.get("virtual_models", [])}

    def available(model):
        profile = model.get("profile")
        if not profile:
            return True
        parent = models.get(profile.get("parent"), {})
        return any(
            profile.get("selector") in implementations.get(target["deployment"], {})
            for pool in parent.get("pools", [])
            for target in pool.get("targets", [])
        )

    document["virtual_models"] = [item for item in document.get("virtual_models", []) if available(item)]
    return document
