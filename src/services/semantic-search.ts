import prisma from "../lib/prisma";
import { generateEmbedding, toVectorLiteral } from "./embeddings";

export interface ChunkMatch {
  chunk_id: string;
  document_name: string;
  relevance_score: number;
  content_preview: string;
  content: string;
}

/**
 * Search for the most relevant chunks across all indexed knowledge bases
 * belonging to the given org. Uses pgvector cosine similarity.
 */
export async function searchKnowledgeBase(
  orgId: string,
  queryText: string,
  topK: number,
  minRelevance: number,
): Promise<ChunkMatch[]> {
  const queryEmbedding = await generateEmbedding(queryText);
  const vectorLiteral = toVectorLiteral(queryEmbedding);

  // Cosine distance: 1 - cosine_similarity. Lower distance = higher relevance.
  // We compute relevance_score = 1 - cosine_distance = cosine_similarity.
  const results = await prisma.$queryRawUnsafe<
    Array<{
      chunk_id: string;
      document_name: string;
      content: string;
      cosine_distance: number;
    }>
  >(
    `SELECT
       c.id AS chunk_id,
       d.filename AS document_name,
       c.content,
       (c.embedding <=> $1::vector) AS cosine_distance
     FROM chunks c
     JOIN documents d ON d.id = c.document_id
     JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
     WHERE kb.org_id = $2
       AND kb.status = 'indexed'
       AND c.embedding IS NOT NULL
     ORDER BY c.embedding <=> $1::vector
     LIMIT $3`,
    vectorLiteral,
    orgId,
    topK,
  );

  return results
    .map((row) => ({
      chunk_id: row.chunk_id,
      document_name: row.document_name,
      relevance_score: Math.round((1 - Number(row.cosine_distance)) * 1000) / 1000,
      content_preview: row.content.slice(0, 100),
      content: row.content,
    }))
    .filter((match) => match.relevance_score >= minRelevance);
}
