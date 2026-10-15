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
