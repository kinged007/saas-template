/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Injected as a literal by vite.config.ts, so the minifier can drop dev notes. */
declare const __DEV_NOTES__: boolean;
