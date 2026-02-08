-- CreateEnum
CREATE TYPE "Plan" AS ENUM ('starter', 'professional', 'enterprise');

-- CreateEnum
CREATE TYPE "Domain" AS ENUM ('legal', 'financial', 'healthcare');

-- CreateEnum
CREATE TYPE "KeyStatus" AS ENUM ('active', 'revoked');

-- CreateEnum
CREATE TYPE "VerificationStatus" AS ENUM ('PASS', 'FLAG', 'BLOCK');

-- CreateEnum
CREATE TYPE "ThreatLevel" AS ENUM ('LOW', 'MEDIUM', 'HIGH');

-- CreateEnum
CREATE TYPE "ThreatAction" AS ENUM ('BLOCK', 'SANITIZE');

-- CreateEnum
CREATE TYPE "ReviewAction" AS ENUM ('approved', 'rejected', 'escalated');

-- CreateTable
CREATE TABLE "organizations" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "plan" "Plan" NOT NULL,
    "domain" "Domain" NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "organizations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "api_keys" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "key_prefix" TEXT NOT NULL,
    "key_hash" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "status" "KeyStatus" NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_used_at" TIMESTAMP(3),

    CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "configurations" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "auto_approve_threshold" INTEGER NOT NULL DEFAULT 85,
    "auto_block_threshold" INTEGER NOT NULL DEFAULT 40,
    "required_checks" JSONB NOT NULL DEFAULT '[]',
    "optional_checks" JSONB NOT NULL DEFAULT '[]',
    "domain_rules" JSONB NOT NULL DEFAULT '{}',
    "notification_settings" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "configurations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "verifications" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "audit_id" TEXT NOT NULL,
    "agent_name" TEXT,
    "model_used" TEXT,
    "domain" "Domain" NOT NULL,
    "user_input" TEXT NOT NULL,
    "ai_output" TEXT NOT NULL,
    "source_context" TEXT,
    "trust_score" INTEGER NOT NULL,
    "status" "VerificationStatus" NOT NULL,
    "checks_results" JSONB NOT NULL,
    "flags" JSONB NOT NULL DEFAULT '[]',
    "human_review_required" BOOLEAN NOT NULL DEFAULT false,
    "reviewed_by" TEXT,
    "review_action" "ReviewAction",
    "review_note" TEXT,
    "reviewed_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "verifications_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "threat_log" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "input_text" TEXT NOT NULL,
    "threat_level" "ThreatLevel" NOT NULL,
    "attack_type" TEXT NOT NULL,
    "action_taken" "ThreatAction" NOT NULL,
    "detail" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "threat_log_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "verifications_audit_id_key" ON "verifications"("audit_id");

-- AddForeignKey
ALTER TABLE "api_keys" ADD CONSTRAINT "api_keys_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "configurations" ADD CONSTRAINT "configurations_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "verifications" ADD CONSTRAINT "verifications_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "threat_log" ADD CONSTRAINT "threat_log_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
