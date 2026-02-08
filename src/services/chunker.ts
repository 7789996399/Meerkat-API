import fs from "fs";
import path from "path";
import crypto from "crypto";
import { PDFParse } from "pdf-parse";
import mammoth from "mammoth";
import prisma from "../lib/prisma";
import { generateEmbedding, toVectorLiteral } from "./embeddings";

const MAX_CHUNK_CHARS = 2000; // ~500 tokens
const TARGET_CHUNK_CHARS = 1200; // ~300 tokens
const OVERLAP_CHARS = 200; // ~50 tokens

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

async function extractText(filePath: string, mimeType: string): Promise<string> {
  switch (mimeType) {
    case "application/pdf": {
      const buffer = fs.readFileSync(filePath);
      const pdf = new PDFParse({ data: buffer });
      const result = await pdf.getText();
      return result.text;
    }
    case "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
      const result = await mammoth.extractRawText({ path: filePath });
      return result.value;
    }
    case "text/plain": {
      return fs.readFileSync(filePath, "utf-8");
    }
    default:
      throw new Error(`Unsupported mime type: ${mimeType}`);
  }
}

function splitBySentence(text: string): string[] {
  // Split on sentence-ending punctuation followed by whitespace
  const sentences = text.match(/[^.!?]+[.!?]+[\s]*/g);
  if (!sentences) return [text];
  return sentences.map((s) => s.trim()).filter((s) => s.length > 0);
}

function splitIntoChunks(text: string): string[] {
  // Step 1: Split by double newline into paragraphs
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => p.length > 0);

  // Step 2: Break large paragraphs into sentences
  const segments: string[] = [];
  for (const para of paragraphs) {
    if (para.length > MAX_CHUNK_CHARS) {
      segments.push(...splitBySentence(para));
    } else {
      segments.push(para);
    }
  }

  // Step 3: Merge small consecutive segments until they reach target size
  const merged: string[] = [];
  let current = "";

  for (const seg of segments) {
    if (current.length === 0) {
      current = seg;
    } else if (current.length + seg.length + 1 <= TARGET_CHUNK_CHARS) {
      current += "\n" + seg;
    } else {
      merged.push(current);
      current = seg;
    }
  }
  if (current.length > 0) {
    merged.push(current);
  }

  // Step 4: Apply overlap between adjacent chunks
  if (merged.length <= 1) return merged;

  const withOverlap: string[] = [merged[0]];
  for (let i = 1; i < merged.length; i++) {
    const prev = merged[i - 1];
    const overlapText = prev.slice(-OVERLAP_CHARS);
    withOverlap.push(overlapText + "\n" + merged[i]);
  }

  return withOverlap;
}

export async function processDocument(documentId: string): Promise<void> {
  const document = await prisma.document.findUniqueOrThrow({
    where: { id: documentId },
    include: { knowledgeBase: true },
  });

  // Update status to chunking
  await prisma.document.update({
    where: { id: documentId },
    data: { status: "chunking" },
  });

  const uploadsDir = path.resolve(__dirname, "../../uploads");
  const filePath = path.join(uploadsDir, `${document.id}_${document.filename}`);

  try {
    const text = await extractText(filePath, document.mimeType);
    const chunks = splitIntoChunks(text);

    // Insert chunks with embeddings via raw SQL (Prisma can't write Unsupported columns)
    for (let i = 0; i < chunks.length; i++) {
      const chunkId = crypto.randomUUID();
      const embedding = await generateEmbedding(chunks[i]);
      const vectorLit = toVectorLiteral(embedding);
      const metadata = JSON.stringify({ chunk_index: i });

      await prisma.$executeRawUnsafe(
        `INSERT INTO chunks (id, document_id, content, chunk_index, embedding, metadata, created_at)
         VALUES ($1, $2, $3, $4, $5::vector, $6::jsonb, NOW())`,
        chunkId,
        document.id,
        chunks[i],
        i,
        vectorLit,
        metadata,
      );
    }

    // Update document status and chunk count
    await prisma.document.update({
      where: { id: documentId },
      data: { status: "indexed", chunkCount: chunks.length },
    });

    // Check if all documents in the KB are indexed, then update KB status
    const pendingDocs = await prisma.document.count({
      where: {
        knowledgeBaseId: document.knowledgeBaseId,
        status: { notIn: ["indexed", "error"] },
      },
    });

    if (pendingDocs === 0) {
      await prisma.knowledgeBase.update({
        where: { id: document.knowledgeBaseId },
        data: { status: "indexed" },
      });
    }

    console.log(`[chunker] Document ${documentId}: ${chunks.length} chunks created`);
  } catch (err) {
    console.error(`[chunker] Error processing document ${documentId}:`, err);

    await prisma.document.update({
      where: { id: documentId },
      data: { status: "error" },
    });

    await prisma.knowledgeBase.update({
      where: { id: document.knowledgeBaseId },
      data: { status: "error" },
    });

    throw err;
  }
}
