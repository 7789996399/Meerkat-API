"""
In-memory data store for demo mode.

In production, these would be backed by DynamoDB or PostgreSQL.
For the demo, we use plain Python dicts. Data is lost on restart
-- that's fine, this is just for local testing and demos.
"""

# audit_id -> AuditRecord (as dict)
# Populated every time /v1/verify is called.
audit_records: dict[str, dict] = {}

# config_id -> GovernanceConfig (as dict)
# Populated when /v1/configure is called.
configs: dict[str, dict] = {}
