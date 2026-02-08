"""
POST /v1/configure -- Domain and org configuration.

Set up your organization's governance rules: risk thresholds,
required checks, domain-specific policies, and alert preferences.

Once configured, pass the returned config_id to /v1/verify and your
custom rules apply automatically instead of the defaults.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from api.models.schemas import ConfigResponse, GovernanceConfig
from api.store import configs

router = APIRouter()


@router.post(
    "/v1/configure",
    response_model=ConfigResponse,
    summary="Create a governance configuration",
    description=(
        "Set up your org's risk tolerances, mandatory checks, and domain-specific rules. "
        "Do this once, then pass the config_id to /v1/verify and your rules apply automatically."
    ),
    tags=["Configuration"],
)
async def configure(config: GovernanceConfig) -> ConfigResponse:
    # Generate a config ID from the org name
    # Format: cfg_{org_id_slug}_{random}
    org_slug = config.org_id.replace(" ", "_").lower()
    config_id = f"cfg_{org_slug}_{uuid.uuid4().hex[:6]}"

    now = datetime.now(timezone.utc)

    # Store the full configuration in memory
    configs[config_id] = {
        "config_id": config_id,
        "org_id": config.org_id,
        "domain": config.domain.value,
        "auto_approve_threshold": config.auto_approve_threshold,
        "auto_block_threshold": config.auto_block_threshold,
        "required_checks": [c.value for c in config.required_checks],
        "optional_checks": [c.value for c in config.optional_checks],
        "domain_rules": config.domain_rules,
        "alerts": config.alerts,
        "created": now.isoformat(),
        "status": "active",
    }

    return ConfigResponse(
        config_id=config_id,
        status="active",
        domain=config.domain,
        created=now,
    )
