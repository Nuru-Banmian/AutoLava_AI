import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

export default async function globalSetup() {
  const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
  const server = await createServer({
    root,
    server: { host: "127.0.0.1", port: 4173, strictPort: true },
  });
  let closePromise: Promise<void> | undefined;
  const close = () => {
    closePromise ??= server.close();
    return closePromise;
  };

  try {
    await server.listen();
  } catch (startupError) {
    try {
      await close();
    } catch (cleanupError) {
      throw new AggregateError(
        [startupError, cleanupError],
        "Vite startup and cleanup both failed",
        { cause: startupError },
      );
    }
    throw startupError;
  }

  return close;
}
