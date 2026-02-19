-- AlterTable
ALTER TABLE "organizations" ADD COLUMN "email" TEXT;

-- CreateIndex
CREATE UNIQUE INDEX "organizations_email_key" ON "organizations"("email");
