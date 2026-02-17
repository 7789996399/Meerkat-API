#!/bin/bash
# ── Meerkat API -- Azure Container Apps Deployment ─────────────────
#
# Deploys the full Meerkat stack:
#   - Azure Container Registry (ACR) for Docker images
#   - Azure Container Apps Environment
#   - PostgreSQL Flexible Server with pgvector
#   - Redis Cache
#   - 5 container apps (node gateway + 4 Python microservices)
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Docker installed
#   - .env.prod file with production secrets
#
# Usage:
#   chmod +x deploy/azure-deploy.sh
#   ./deploy/azure-deploy.sh
#
# Estimated time: 15-20 minutes
# Estimated cost: ~$150-250/month (Standard tier)

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────

RESOURCE_GROUP="${MEERKAT_RG:-meerkat-prod}"
LOCATION="${MEERKAT_LOCATION:-canadacentral}"
ACR_NAME="${MEERKAT_ACR:-meerkatacr}"
ENV_NAME="${MEERKAT_ENV:-meerkat-env}"
LOG_ANALYTICS="${MEERKAT_LA:-meerkat-logs}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[MEERKAT]${NC} $1"; }
warn() { echo -e "${YELLOW}[MEERKAT]${NC} $1"; }
err()  { echo -e "${RED}[MEERKAT]${NC} $1"; exit 1; }

# ── Preflight Checks ──────────────────────────────────────────────

log "Running preflight checks..."

command -v az   >/dev/null 2>&1 || err "Azure CLI not found. Install: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
command -v docker >/dev/null 2>&1 || err "Docker not found. Install: https://docs.docker.com/get-docker/"

# Check Azure login
az account show >/dev/null 2>&1 || err "Not logged in to Azure. Run: az login"

# Check .env.prod exists
if [ ! -f .env.prod ]; then
  err ".env.prod not found. Copy .env.prod.template to .env.prod and fill in values."
fi

# Load environment variables
set -a
source .env.prod
set +a

log "Deploying to: $LOCATION (resource group: $RESOURCE_GROUP)"
log "Container registry: $ACR_NAME"

# ── Step 1: Create Resource Group ──────────────────────────────────

log "Step 1/8: Creating resource group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── Step 2: Create Container Registry ─────────────────────────────

log "Step 2/8: Creating container registry..."
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true \
  --output none

# Get ACR credentials
ACR_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

log "ACR server: $ACR_SERVER"

# ── Step 3: Build and Push Docker Images ───────────────────────────

log "Step 3/8: Building and pushing Docker images..."

# Login to ACR
az acr login --name "$ACR_NAME"

# Build and push each image
IMAGES=(
  "meerkat-node:Dockerfile.node:."
  "meerkat-entropy:meerkat-semantic-entropy/Dockerfile:meerkat-semantic-entropy"
  "meerkat-claims:meerkat-claim-extractor/Dockerfile:meerkat-claim-extractor"
  "meerkat-preference:meerkat-implicit-preference/Dockerfile:meerkat-implicit-preference"
  "meerkat-numerical:meerkat-numerical-verify/Dockerfile:meerkat-numerical-verify"
)

for img_spec in "${IMAGES[@]}"; do
  IFS=: read -r name dockerfile context <<< "$img_spec"
  log "  Building $name..."
  docker build -t "$ACR_SERVER/$name:latest" -f "$dockerfile" "$context"
  docker push "$ACR_SERVER/$name:latest"
done

log "All images pushed to $ACR_SERVER"

# ── Step 4: Create Log Analytics Workspace ─────────────────────────

log "Step 4/8: Creating Log Analytics workspace..."
az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --output none

LA_CUSTOMER_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query customerId -o tsv)

LA_SHARED_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query primarySharedKey -o tsv)

# ── Step 5: Create Container Apps Environment ──────────────────────

log "Step 5/8: Creating Container Apps environment..."
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --logs-workspace-id "$LA_CUSTOMER_ID" \
  --logs-workspace-key "$LA_SHARED_KEY" \
  --output none

# ── Step 6: Create PostgreSQL Flexible Server ──────────────────────

log "Step 6/8: Creating PostgreSQL server..."
PG_SERVER_NAME="${RESOURCE_GROUP}-pgserver"

az postgres flexible-server create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$PG_SERVER_NAME" \
  --location "$LOCATION" \
  --admin-user "$POSTGRES_USER" \
  --admin-password "$POSTGRES_PASSWORD" \
  --database-name "$POSTGRES_DB" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16 \
  --yes \
  --output none

# Enable pgvector extension
az postgres flexible-server parameter set \
  --resource-group "$RESOURCE_GROUP" \
  --server-name "$PG_SERVER_NAME" \
  --name azure.extensions \
  --value vector \
  --output none

PG_FQDN=$(az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$PG_SERVER_NAME" \
  --query fullyQualifiedDomainName -o tsv)

DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${PG_FQDN}:5432/${POSTGRES_DB}?sslmode=require"
log "PostgreSQL: $PG_FQDN"

# ── Step 7: Deploy Internal Microservices ──────────────────────────

log "Step 7/8: Deploying microservices..."

# Numerical verify (lightest, deploy first)
az containerapp create \
  --name meerkat-numerical \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_SERVER/meerkat-numerical:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8004 \
  --ingress internal \
  --cpu 0.25 --memory 0.5Gi \
  --min-replicas 1 --max-replicas 3 \
  --env-vars "MEERKAT_LOG_LEVEL=info" \
  --output none

# Semantic entropy (heaviest -- DeBERTa model)
az containerapp create \
  --name meerkat-entropy \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_SERVER/meerkat-entropy:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8001 \
  --ingress internal \
  --cpu 2 --memory 4Gi \
  --min-replicas 1 --max-replicas 5 \
  --env-vars "MEERKAT_LOG_LEVEL=info" \
  --output none

# Claim extractor (spaCy transformer model)
az containerapp create \
  --name meerkat-claims \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_SERVER/meerkat-claims:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8002 \
  --ingress internal \
  --cpu 1 --memory 3Gi \
  --min-replicas 1 --max-replicas 3 \
  --env-vars "MEERKAT_LOG_LEVEL=info ENTAILMENT_URL=http://meerkat-entropy/predict" \
  --output none

# Implicit preference (DistilBERT)
az containerapp create \
  --name meerkat-preference \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_SERVER/meerkat-preference:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8003 \
  --ingress internal \
  --cpu 1 --memory 2Gi \
  --min-replicas 1 --max-replicas 3 \
  --env-vars "MEERKAT_LOG_LEVEL=info" \
  --output none

# ── Step 8: Deploy Node Gateway (public) ──────────────────────────

log "Step 8/8: Deploying API gateway..."

az containerapp create \
  --name meerkat-node \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_SERVER/meerkat-node:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 3000 \
  --ingress external \
  --cpu 1 --memory 2Gi \
  --min-replicas 1 --max-replicas 10 \
  --env-vars \
    "PORT=3000" \
    "NODE_ENV=production" \
    "DATABASE_URL=$DATABASE_URL" \
    "REDIS_URL=redis://redis:6379" \
    "ENTROPY_SERVICE_URL=http://meerkat-entropy" \
    "CLAIMS_SERVICE_URL=http://meerkat-claims" \
    "PREFERENCE_SERVICE_URL=http://meerkat-preference" \
    "NUMERICAL_SERVICE_URL=http://meerkat-numerical" \
    "JWT_SECRET=$JWT_SECRET" \
    "STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}" \
    "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-}" \
    "FRONTEND_URL=${FRONTEND_URL:-https://app.meerkat.ai}" \
    "MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID:-}" \
    "MICROSOFT_CLIENT_SECRET=${MICROSOFT_CLIENT_SECRET:-}" \
    "MICROSOFT_TENANT_ID=${MICROSOFT_TENANT_ID:-}" \
    "OPENAI_API_KEY=${OPENAI_API_KEY:-}" \
  --output none

# ── Get Public URL ─────────────────────────────────────────────────

API_URL=$(az containerapp show \
  --name meerkat-node \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
log "=========================================="
log "  Meerkat API deployed successfully!"
log "=========================================="
log ""
log "  API URL: https://$API_URL"
log "  Health:  https://$API_URL/v1/health"
log ""
log "  Next steps:"
log "  1. Run database migrations:"
log "     DATABASE_URL=\"$DATABASE_URL\" npx prisma migrate deploy"
log "  2. Seed demo data (optional):"
log "     DATABASE_URL=\"$DATABASE_URL\" npx tsx prisma/seed.ts"
log "  3. Set up custom domain:"
log "     az containerapp hostname add --name meerkat-node -g $RESOURCE_GROUP --hostname api.meerkat.ai"
log "  4. Configure Stripe webhook to:"
log "     https://$API_URL/v1/billing/webhook"
log ""
log "  Resource group: $RESOURCE_GROUP"
log "  Container registry: $ACR_SERVER"
log "  PostgreSQL: $PG_FQDN"
log ""
