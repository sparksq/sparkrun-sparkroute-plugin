#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
#
# SparkRoute plugin development setup. Usage: source dev.sh
# Optional combined host: export SPARKRUN_DEV_COLDSNAP=1 before sourcing.
# The assembler fetches coldsnap unless SPARKRUN_COLDSNAP_CHECKOUT is supplied.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "dev.sh must be sourced: source dev.sh" >&2
    exit 1
fi

_sparkrun_sparkroute_host_supported() {
    grep -q "def catalog_cluster_capacity(" "$1/src/sparkrun/api/_catalog.py" 2>/dev/null &&
        grep -q "def native_api_options(" "$1/src/sparkrun/runtimes/base.py" 2>/dev/null &&
        grep -q '^OPENAI_RESPONSES_STREAM =' "$1/src/sparkrun/core/readiness.py" 2>/dev/null &&
        grep -q 'affects_fingerprint: bool = True' "$1/src/sparkrun/core/recipe_items.py" 2>/dev/null &&
        grep -q 'def export_plugin_items(' "$1/src/sparkrun/core/recipe.py" 2>/dev/null &&
        grep -q 'engine._await_exit(pid, RESTART_WAIT_SECONDS)' "$1/src/sparkrun/api/proxy/_ops.py" 2>/dev/null
}

_sparkrun_sparkroute_dev_setup() {
    local script_dir
    local venv_dir
    local checkout
    local checkout_origin
    local checkout_override
    local dev_checkout
    local gateway_binary
    local legacy_binary_env
    local branch
    local managed_checkout=0
    local repository="https://github.com/spark-arena/sparkrun.git"

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || return 1
    venv_dir="$script_dir/.venv"
    dev_checkout="$script_dir/.dev/sparkrun-with-sparkroute"
    branch="${SPARKRUN_BRANCH:-develop-next}"
    checkout_override="${SPARKRUN_CHECKOUT:-}"

    # A managed setup exports its resolved path for the test bootstrap. On a
    # later `source dev.sh`, do not mistake that output for a user-supplied
    # override; otherwise changing only SPARKRUN_BRANCH silently keeps using
    # the previously selected commit. Recognize the default path directly for
    # shells initialized by older versions that did not export the marker.
    if [[ "$checkout_override" == "$script_dir/.dev/sparkrun" ]] || \
        [[ -n "${_SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT:-}" && "$checkout_override" == "$_SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT" ]]; then
        checkout_override=""
    fi

    if ! command -v uv >/dev/null 2>&1; then
        echo "uv is not installed. Install it from https://docs.astral.sh/uv/" >&2
        return 1
    fi

    if ! command -v git >/dev/null 2>&1; then
        echo "git is required to prepare the sparkrun checkout." >&2
        return 1
    fi

    if [[ -n "$checkout_override" ]]; then
        checkout="$checkout_override"
        if [[ ! -d "$checkout" ]]; then
            echo "SPARKRUN_CHECKOUT is not a directory: $checkout" >&2
            return 1
        fi
        checkout="$(cd "$checkout" && pwd -P)" || return 1
        echo "Using local sparkrun checkout: $checkout"
    else
        checkout="$script_dir/.dev/sparkrun"
        managed_checkout=1

        if ! git check-ref-format --branch "$branch" >/dev/null 2>&1; then
            echo "SPARKRUN_BRANCH is not a valid Git branch name: $branch" >&2
            return 1
        fi

        if [[ -e "$checkout" && ! -e "$checkout/.git" ]]; then
            echo "Managed checkout path exists but is not a Git repository: $checkout" >&2
            return 1
        fi

        if [[ ! -e "$checkout/.git" ]]; then
            mkdir -p "$(dirname "$checkout")" || return 1
            echo "Cloning sparkrun branch $branch from $repository ..."
            git clone --single-branch --branch "$branch" "$repository" "$checkout" || return 1
        elif [[ -f "$checkout/.git" ]]; then
            echo "Using project sparkrun worktree without changing its branch: $checkout"
            managed_checkout=0
        else
            checkout_origin="$(git -C "$checkout" remote get-url origin)" || return 1
            if [[ "$checkout_origin" != "$repository" ]]; then
                echo "Managed checkout has an unexpected origin: $checkout_origin" >&2
                echo "Expected: $repository" >&2
                return 1
            fi
            if [[ -n "$(git -C "$checkout" status --porcelain)" ]]; then
                echo "Managed sparkrun checkout has local changes; refusing to update: $checkout" >&2
                return 1
            fi
            echo "Updating sparkrun branch $branch from $repository ..."
            git -C "$checkout" fetch --prune origin "$branch" || return 1
            git -C "$checkout" switch --detach FETCH_HEAD || return 1
        fi
    fi

    # A shared shell may still point at an older ColdSnap development host.
    # Prefer this project's compatible local worktree when that host lacks the
    # recipe catalog and shared native API/readiness support.
    if ! _sparkrun_sparkroute_host_supported "$checkout" && _sparkrun_sparkroute_host_supported "$script_dir/.dev/sparkrun"; then
        echo "Selected host lacks current catalog, recipe, and restart support; using this project's sparkrun checkout."
        checkout="$script_dir/.dev/sparkrun"
        managed_checkout=0
    fi

    if [[ ! -f "$checkout/pyproject.toml" || ! -f "$checkout/src/sparkrun/__init__.py" ]]; then
        echo "Selected path is not a sparkrun checkout: $checkout" >&2
        return 1
    fi

    if ! _sparkrun_sparkroute_host_supported "$checkout"; then
        echo "This sparkrun checkout lacks current catalog, recipe, and restart support. Select the host commit in compat/host.toml via SPARKRUN_CHECKOUT." >&2
        return 1
    fi

    export SPARKRUN_CHECKOUT="$checkout"
    export SPARKRUN_BRANCH="$branch"
    if (( managed_checkout )); then
        export _SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT="$checkout"
    else
        unset _SPARKRUN_SPARKROUTE_MANAGED_CHECKOUT
    fi

    if [[ ! -x "$venv_dir/bin/python" ]]; then
        echo "Creating the SparkRoute plugin environment with uv ..."
        uv venv "$venv_dir" || return 1
    fi

    echo "Assembling SparkRoute and any selected coldsnap plugin into a disposable sparkrun tree ..."
    "$venv_dir/bin/python" "$script_dir/scripts/assemble-dev-host.py" \
        --host "$checkout" --destination "$dev_checkout" || return 1
    export SPARKRUN_DEV_CHECKOUT="$dev_checkout"

    echo "Installing the assembled sparkrun checkout as an editable dependency ..."
    uv pip install --python "$venv_dir/bin/python" --editable "$dev_checkout[dev]" || return 1

    echo "Installing the SparkRoute plugin and its development tools ..."
    uv pip install --python "$venv_dir/bin/python" --project "$script_dir" --group dev || return 1
    uv pip install --python "$venv_dir/bin/python" --no-deps --editable "$script_dir" || return 1

    if ! uv pip check --python "$venv_dir/bin/python"; then
        echo "The selected sparkrun checkout does not satisfy the plugin's declared compatibility range." >&2
        echo "Select a compatible branch with SPARKRUN_BRANCH or use SPARKRUN_CHECKOUT." >&2
        return 1
    fi

    # shellcheck disable=SC1091
    source "$venv_dir/bin/activate" || return 1

    if [[ -z "${SPARKRUN_SPARKROUTE_BINARY:-}" ]]; then
        for legacy_binary_env in SPARKRUN_FOXSCI_ROUTE_BINARY SPARKRUN_LLM_GATEWAY_BINARY; do
            if [[ -n "${!legacy_binary_env:-}" ]]; then
                export SPARKRUN_SPARKROUTE_BINARY="${!legacy_binary_env}"
                echo "$legacy_binary_env is deprecated; use SPARKRUN_SPARKROUTE_BINARY." >&2
                break
            fi
        done
    fi

    # A previous setup's export is managed output: revalidate it so changing
    # the paired source pin cannot silently leave an older binary selected.
    if [[ -n "${SPARKRUN_SPARKROUTE_BINARY:-}" && \
          "${SPARKRUN_SPARKROUTE_BINARY}" != "${_SPARKRUN_SPARKROUTE_MANAGED_BINARY:-}" ]]; then
        if [[ ! -f "$SPARKRUN_SPARKROUTE_BINARY" || ! -x "$SPARKRUN_SPARKROUTE_BINARY" ]]; then
            echo "SPARKRUN_SPARKROUTE_BINARY must name an executable file: $SPARKRUN_SPARKROUTE_BINARY" >&2
            return 1
        fi
        echo "Using explicit SparkRoute development binary: $SPARKRUN_SPARKROUTE_BINARY"
        unset _SPARKRUN_SPARKROUTE_MANAGED_BINARY
    else
        echo "Preparing the pinned SparkRoute development binary ..."
        gateway_binary="$("$venv_dir/bin/python" "$script_dir/scripts/prepare-dev-gateway.py")" || return 1
        if [[ ! -f "$gateway_binary" || ! -x "$gateway_binary" ]]; then
            echo "SparkRoute development setup did not produce an executable: $gateway_binary" >&2
            return 1
        fi
        export SPARKRUN_SPARKROUTE_BINARY="$gateway_binary"
        export _SPARKRUN_SPARKROUTE_MANAGED_BINARY="$gateway_binary"
    fi

    echo "Updating recipe registries ..."
    if ! "$venv_dir/bin/sparkrun" registry update; then
        echo "Warning: registry update failed (non-fatal)." >&2
    fi

    echo "Installing pre-commit hooks ..."
    if ! (cd "$script_dir" && "$venv_dir/bin/pre-commit" install); then
        echo "Warning: pre-commit hook installation failed." >&2
    fi

    if (( managed_checkout )); then
        echo "Using managed sparkrun $branch checkout at $checkout"
    fi
    echo "Done. The SparkRoute plugin development environment is active."
}

_sparkrun_sparkroute_dev_cleanup() {
    local status="$1"
    unset -f _sparkrun_sparkroute_dev_setup _sparkrun_sparkroute_dev_cleanup _sparkrun_sparkroute_host_supported
    return "$status"
}

_sparkrun_sparkroute_dev_setup
_sparkrun_sparkroute_dev_cleanup "$?"
return $?
