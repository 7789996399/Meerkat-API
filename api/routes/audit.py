"""
GET /v1/audit/{audit_id} -- Compliance audit trail.

Retrieves the full governance record for a past verification.
Every call to /v1/verify automatically creates an audit record.

In production, these records would be stored in DynamoDB or PostgreSQL
with encryption at rest. For the demo, they live in an in-memory dict.
"""

from fastapi import APIRouter, HTTPException

from api.models.schemas import AuditRecord
from api.store import audit_records

router = APIRouter()


@router.get(
    "/v1/audit/{audit_id}",
    response_model=AuditRecord,
    summary="Retrieve an audit record",
    description=(
        "Look up the full governance record for a past verification. "
        "The audit_id is returned by /v1/verify in every response. "
        "These records are immutable -- they cannot be modified or deleted."
    ),
    tags=["Compliance"],
)
async def get_audit(audit_id: str) -> AuditRecord:
    record = audit_records.get(audit_id)

    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Audit record '{audit_id}' not found. Records are stored in memory and lost on server restart.",
        )

    return AuditRecord(**record)
