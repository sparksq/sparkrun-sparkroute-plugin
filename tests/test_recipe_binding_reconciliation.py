# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

from copy import deepcopy

from sparkrun.plugins.sparkroute.reconciliation import retain_recipe_bindings


def document(revision="old", name="saved-id"):
    return {
        "providers": [{"name": "sparkrun", "type": "sparkrun"}],
        "deployments": [
            {
                "name": name,
                "model": "model",
                "endpoint_source": {
                    "type": "activatable",
                    "controller": "sparkrun",
                    "recipe": "@registry/recipe",
                    "recipe_revision": revision,
                    "revision": "binding-" + revision,
                    "cluster_candidates": ["lab"],
                    "overrides": {"max_model_len": "4096"},
                },
            }
        ],
        "virtual_models": [{"name": "model", "aliases": ["alias"], "pools": [{"targets": [{"deployment": name, "weight": 1}]}]}],
    }


def test_catalog_drift_keeps_pin_and_references_until_gateway_reconciles():
    previous = document()
    desired = document("new", "fingerprint-id")
    snapshot = deepcopy(desired)
    result = retain_recipe_bindings(desired, previous)
    assert result == previous
    assert desired == snapshot


def test_after_gateway_update_reconcile_keeps_stable_deployment_id():
    previous = document("new")
    desired = document("new", "fingerprint-id")
    desired["deployments"][0]["title"] = "New display title"
    result = retain_recipe_bindings(desired, previous)
    assert result["deployments"][0]["name"] == "saved-id"
    assert result["deployments"][0]["title"] == "New display title"
    assert result["virtual_models"] == previous["virtual_models"]


def test_explicit_binding_edits_are_not_held_back():
    for field, value in [("recipe", "other"), ("overrides", {"max_model_len": "8192"}), ("cluster_candidates", ["other"])]:
        desired = document("new", "new-id")
        desired["deployments"][0]["endpoint_source"][field] = value
        assert retain_recipe_bindings(desired, document()) == desired


def test_unapplied_profiles_are_not_published_and_discovery_is_untouched():
    desired = document("new", "new-id")
    desired["deployments"][0]["request_profiles"] = {"low": {}}
    desired["virtual_models"].append({"name": "model:low", "profile": {"parent": "model", "selector": "low"}})
    desired["deployments"].append({"name": "discovered", "endpoint_source": {"type": "discovered"}})
    result = retain_recipe_bindings(desired, document())
    assert result["virtual_models"] == document()["virtual_models"]
    assert result["deployments"][-1] == desired["deployments"][-1]
