const DEFAULT_PORT = 5317;

type Env = Record<string, string | undefined>;

export type E2EServer = {
  port: number;
  baseURL: string;
  reuse: boolean;
};

// The e2e specs mock every /api/v1 call, so a run needs nothing but its own vite
// server. Reuse is opt-in: attaching to whatever already holds the port can serve
// another checkout's tree, which passes the suite against the wrong code.
export function e2eServer(env: Env = process.env): E2EServer {
  const port = Number(env.E2E_PORT) || DEFAULT_PORT;
  return {
    port,
    baseURL: `http://127.0.0.1:${port}`,
    reuse: env.E2E_REUSE_SERVER === "1",
  };
}