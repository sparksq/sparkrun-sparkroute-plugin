# SPDX-FileCopyrightText: 2026 Scitrera LLC
# SPDX-FileCopyrightText: 2026 Fox Engine Ltd
# SPDX-License-Identifier: AGPL-3.0-only
# Additional permission under AGPLv3 section 7: see src/sparkrun/plugins/sparkroute/LICENSE_EXCEPTION.

"""Explicit SparkRoute capability activation, using the shared host policy."""

from sparkrun.plugins import select_gateway


def enable_feature(context):
    if context.feature == "gateway.sparkroute":
        return select_gateway(context, "sparkroute")
