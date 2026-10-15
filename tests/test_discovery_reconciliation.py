# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""A duplicate public name must not hide a discovered deployment."""

from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from sparkrun.plugins.sparkroute.admin import AdminClient, AdminError, RevisionConflict
from sparkrun.plugins.sparkroute.engine import SparkrouteEngine
from sparkrun.plugins.sparkroute.reconciliation import prepare_discovery_routes


def document():
    return {
        "providers": [{"name": "sparkrun", "type": "sparkrun"}],
        "deployments": [
            {"name": name, "provider": "sparkrun", "model": model, "endpoint_source": {"type": "discovered", "controller": "sparkrun"}}
            for name, model in [("new", "deepseek"), ("other", "other-model")]
        ],
        "virtual_models": [
            {"name": model, "pools": [{"targets": [{"deployment": name, "weight": 1}]}]}
            for name, model in [("new", "deepseek"), ("other", "other-model")]
        ],
    }


def context(*, current=None, referenced=(), revision="a", kind="model"):
    return {
        "active_revision": revision,
        "document": current or {},
        "reserved_names": [{"name": "deepseek", "owner": "operator", "model": "saved-route", "kind": kind}],
        "referenced_deployments": list(referenced),
    }


@pytest.mark.parametrize("kind", ["model", "alias"])
def test_conflict_keeps_deployment_and_unrelated_routes(kind):
    original = document()
    snapshot = deepcopy(original)
    result, warnings = prepare_discovery_routes(original, context(kind=kind))
    assert result["deployments"] == original["deployments"]
    assert [m["name"] for m in result["virtual_models"]] == ["other-model"]
    assert len(warnings) == 1 and "operator" in warnings[0] and "saved-route" in warnings[0]
    assert original == snapshot


def test_explicit_binding_name_conflicts_still_reach_gateway_validation():
    original = document()
    original["deployments"][0]["endpoint_source"]["type"] = "activatable"
    result, warnings = prepare_discovery_routes(original, context())
    assert result == original and not warnings


def test_conflicting_alias_does_not_hide_its_nonconflicting_route():
    original = document()
    original["virtual_models"][0]["name"] = "available"
    original["virtual_models"][0]["aliases"] = ["deepseek", "free"]
    result, warnings = prepare_discovery_routes(original, context())
    assert result["virtual_models"][0]["aliases"] == ["free"]
    assert len(warnings) == 1


def test_profiles_of_withheld_route_cannot_attach_to_operator_parent():
    original = document()
    original["virtual_models"].append({"name": "deepseek:low", "profile": {"parent": "deepseek", "selector": "low"}})
    result, _ = prepare_discovery_routes(original, context())
    assert [m["name"] for m in result["virtual_models"]] == ["other-model"]


def test_operator_correction_and_stopped_workload_survive_future_sweeps():
    first, _ = prepare_discovery_routes(document(), context())
    corrected = context(current=first, referenced=["new"])
    second, warnings = prepare_discovery_routes(document(), corrected)
    assert second == first and not warnings
    empty = {"providers": first["providers"], "deployments": [], "virtual_models": []}
    stopped, warnings = prepare_discovery_routes(empty, corrected)
    assert [d["name"] for d in stopped["deployments"]] == ["new"]
    assert stopped["deployments"][0] == first["deployments"][0]
    assert not warnings
    unreferenced, _ = prepare_discovery_routes(empty, context(current=stopped))
    assert unreferenced["deployments"] == []


def test_reconcile_rebuilds_claims_after_concurrent_operator_edit(tmp_path):
    engine = SparkrouteEngine(state_dir=tmp_path)
    client = Mock()
    after_edit = context(revision="b")
    after_edit["reserved_names"] = []
    client.reconciliation_context.side_effect = [context(), after_edit]
    client.replace.side_effect = [RevisionConflict("changed", status=409), {"changed": True}]
    with (
        patch.object(engine, "admin_client", return_value=client),
        patch.object(engine, "build_desired_set", side_effect=lambda *_: document()),
        patch.object(engine, "_await_serving_config"),
        patch("sparkrun.plugins.sparkroute.engine.time.sleep"),
    ):
        engine.reconcile()
    first, second = client.replace.call_args_list
    assert first.args[1] == "a" and second.args[1] == "b"
    assert [m["name"] for m in first.args[0]["virtual_models"]] == ["other-model"]
    assert [m["name"] for m in second.args[0]["virtual_models"]] == ["deepseek", "other-model"]
    assert not engine.discovery_warnings()


@pytest.mark.parametrize("status", [404, 501, 403, 500])
def test_old_gateway_fallback_does_not_hide_auth_or_transport_failures(status):
    client = AdminClient("http://localhost", None)
    with patch.object(client, "_request", side_effect=AdminError("unavailable", status=status)):
        if status in (404, 501):
            assert client.reconciliation_context() is None
        else:
            with pytest.raises(AdminError):
                client.reconciliation_context()


def test_reconciliation_context_rejects_malformed_claims():
    client = AdminClient("http://localhost", None)
    value = context()
    value["reserved_names"] = [{"name": "deepseek"}]
    with patch.object(client, "_request", return_value=value), pytest.raises(AdminError, match="invalid reconciliation context"):
        client.reconciliation_context()


def test_stopped_generated_parent_used_by_operator_profile_is_retained():
    current = document()
    snapshot = context(current=current, referenced=["new"])
    snapshot["reserved_names"] = []
    snapshot["referenced_models"] = ["deepseek"]
    empty = {"providers": current["providers"], "deployments": [], "virtual_models": []}
    result, warnings = prepare_discovery_routes(empty, snapshot)
    assert [d["name"] for d in result["deployments"]] == ["new"]
    assert [m["name"] for m in result["virtual_models"]] == ["deepseek"]
    assert not warnings


def test_inherited_profile_alias_conflict_only_withholds_optional_profile():
    original = document()
    original["virtual_models"][0]["aliases"] = ["shortcut"]
    original["virtual_models"].append({"name": "deepseek:low", "profile": {"parent": "deepseek", "selector": "low"}})
    snapshot = context()
    snapshot["reserved_names"][0]["name"] = "shortcut:low"
    result, warnings = prepare_discovery_routes(original, snapshot)
    assert [model["name"] for model in result["virtual_models"]] == ["deepseek", "other-model"]
    assert result["deployments"] == original["deployments"]
    assert len(warnings) == 1 and "shortcut:low" in warnings[0]
