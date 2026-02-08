-- CreateExtension
CREATE EXTENSION IF NOT EXISTS "vector";

-- AlterTable: drop old Json? embedding column and add vector(1536)
ALTER TABLE "chunks" DROP COLUMN IF EXISTS "embedding";
ALTER TABLE "chunks" ADD COLUMN "embedding" vector(1536);

-- AlterTable: add KB config fields to configurations
ALTER TABLE "configurations" ADD COLUMN "knowledge_base_enabled" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "configurations" ADD COLUMN "kb_top_k" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "configurations" ADD COLUMN "kb_min_relevance" DOUBLE PRECISION NOT NULL DEFAULT 0.75;

-- CreateIndex: HNSW index for cosine similarity search
CREATE INDEX "chunks_embedding_idx" ON "chunks" USING hnsw ("embedding" vector_cosine_ops);
