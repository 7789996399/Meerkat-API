-- AlterEnum
ALTER TYPE "ThreatLevel" ADD VALUE 'CRITICAL';

-- AlterTable
ALTER TABLE "threat_log" ADD COLUMN     "audit_id" TEXT,
ADD COLUMN     "remediation" JSONB,
ADD COLUMN     "sanitized_input" TEXT,
ADD COLUMN     "session_id" TEXT,
ADD COLUMN     "threats" JSONB;

-- AlterTable
ALTER TABLE "verification_sessions" ADD COLUMN     "type" TEXT NOT NULL DEFAULT 'verify';

-- CreateIndex
CREATE UNIQUE INDEX "threat_log_audit_id_key" ON "threat_log"("audit_id");

-- AddForeignKey
ALTER TABLE "threat_log" ADD CONSTRAINT "threat_log_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "verification_sessions"("session_id") ON DELETE SET NULL ON UPDATE CASCADE;
