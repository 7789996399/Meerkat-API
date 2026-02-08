// TODO: Replace with Bull/BullMQ backed by Redis for production

type JobHandler = () => Promise<void>;

interface Job {
  name: string;
  handler: JobHandler;
}

const queue: Job[] = [];
let processing = false;

async function processQueue(): Promise<void> {
  if (processing) return;
  processing = true;

  while (queue.length > 0) {
    const job = queue.shift()!;
    try {
      console.log(`[job-queue] Processing job: ${job.name}`);
      await job.handler();
      console.log(`[job-queue] Completed job: ${job.name}`);
    } catch (err) {
      console.error(`[job-queue] Failed job: ${job.name}`, err);
    }
  }

  processing = false;
}

export function enqueue(name: string, handler: JobHandler): void {
  queue.push({ name, handler });
  setTimeout(processQueue, 0);
}
