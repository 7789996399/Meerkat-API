// TODO: Replace with real embedding model (e.g. OpenAI text-embedding-3-small,
// or local sentence-transformers via ONNX). The stub returns a random unit vector
// so that pgvector cosine similarity queries work end-to-end during development.

const DIMENSIONS = 1536;

export async function generateEmbedding(text: string): Promise<number[]> {
  // Generate a random vector
  const raw = Array.from({ length: DIMENSIONS }, () => Math.random() * 2 - 1);

  // Normalize to unit length so cosine similarity is meaningful
  const magnitude = Math.sqrt(raw.reduce((sum, v) => sum + v * v, 0));
  return raw.map((v) => v / magnitude);
}

/**
 * Format a number[] as a pgvector-compatible string literal: '[0.1,0.2,...]'
 */
export function toVectorLiteral(embedding: number[]): string {
  return `[${embedding.join(",")}]`;
}
