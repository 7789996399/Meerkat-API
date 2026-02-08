import { Router } from "express";
import multer from "multer";
import path from "path";
import fs from "fs";
import { AuthenticatedRequest } from "../middleware/auth";
import { processDocument } from "../services/chunker";
import { enqueue } from "../services/job-queue";
import prisma from "../lib/prisma";

const router = Router();

const ALLOWED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];

const uploadsDir = path.resolve(__dirname, "../../uploads");
if (!fs.existsSync(uploadsDir)) {
  fs.mkdirSync(uploadsDir, { recursive: true });
}

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, uploadsDir),
    filename: (_req, file, cb) => {
      // Temporary name; will be renamed after document record is created
      cb(null, `tmp_${Date.now()}_${file.originalname}`);
    },
  }),
  limits: { fileSize: 50 * 1024 * 1024 }, // 50MB
  fileFilter: (_req, file, cb) => {
    if (ALLOWED_MIME_TYPES.includes(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error(`Unsupported file type: ${file.mimetype}. Accepted: PDF, DOCX, TXT`));
    }
  },
});

// POST /v1/knowledge-base/upload
router.post("/upload", upload.single("file"), async (req: AuthenticatedRequest, res) => {
  try {
    if (!req.file) {
      res.status(400).json({ error: "No file uploaded. Use field name 'file'." });
      return;
    }

    const orgId = req.context!.orgId;
    const kbName = req.body.name || req.file.originalname;

    // Create or find existing KnowledgeBase for this org with this name
    let knowledgeBase = await prisma.knowledgeBase.findFirst({
      where: { orgId, name: kbName },
    });

    if (!knowledgeBase) {
      knowledgeBase = await prisma.knowledgeBase.create({
        data: { orgId, name: kbName, status: "processing" },
      });
    } else {
      // Reset to processing when adding a new document
      await prisma.knowledgeBase.update({
        where: { id: knowledgeBase.id },
        data: { status: "processing" },
      });
    }

    // Create document record
    const document = await prisma.document.create({
      data: {
        knowledgeBaseId: knowledgeBase.id,
        filename: req.file.originalname,
        fileSize: req.file.size,
        mimeType: req.file.mimetype,
        status: "uploaded",
      },
    });

    // Rename temp file to final name: {document_id}_{original_filename}
    const finalPath = path.join(uploadsDir, `${document.id}_${req.file.originalname}`);
    fs.renameSync(req.file.path, finalPath);

    // Enqueue chunking job
    enqueue(`chunk-${document.id}`, () => processDocument(document.id));

    res.status(201).json({
      document_id: document.id,
      knowledge_base_id: knowledgeBase.id,
      status: "processing",
    });
  } catch (err: any) {
    console.error("[knowledge-base] Upload error:", err);
    res.status(500).json({ error: err.message || "Upload failed" });
  }
});

// GET /v1/knowledge-base
router.get("/", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;

  const knowledgeBases = await prisma.knowledgeBase.findMany({
    where: { orgId },
    include: {
      documents: {
        select: {
          id: true,
          filename: true,
          status: true,
          chunkCount: true,
          fileSize: true,
          mimeType: true,
          uploadedAt: true,
        },
      },
    },
    orderBy: { createdAt: "desc" },
  });

  res.json({ knowledge_bases: knowledgeBases });
});

// GET /v1/knowledge-base/:documentId
router.get("/:documentId", async (req: AuthenticatedRequest, res) => {
  const orgId = req.context!.orgId;
  const documentId = req.params.documentId as string;

  const document = await prisma.document.findFirst({
    where: {
      id: documentId,
      knowledgeBase: { orgId },
    },
  });

  if (!document) {
    res.status(404).json({ error: "Document not found" });
    return;
  }

  const previewChunks = await prisma.chunk.findMany({
    where: { documentId: document.id },
    take: 5,
    orderBy: { chunkIndex: "asc" },
    select: {
      id: true,
      chunkIndex: true,
      content: true,
      metadata: true,
    },
  });

  res.json({
    id: document.id,
    filename: document.filename,
    file_size: document.fileSize,
    mime_type: document.mimeType,
    status: document.status,
    chunk_count: document.chunkCount,
    uploaded_at: document.uploadedAt,
    preview_chunks: previewChunks,
  });
});

export default router;
