import { Router } from "express";
import shieldRouter from "./shield";
import verifyRouter from "./verify";
import auditRouter from "./audit";
import configureRouter from "./configure";
import dashboardRouter from "./dashboard";
import knowledgeBaseRouter from "./knowledge-base";
import billingRouter from "./billing";

const router = Router();

router.use("/shield", shieldRouter);
router.use("/verify", verifyRouter);
router.use("/audit", auditRouter);
router.use("/configure", configureRouter);
router.use("/dashboard", dashboardRouter);
router.use("/knowledge-base", knowledgeBaseRouter);
router.use("/billing", billingRouter);

export default router;
