import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies nothing and there is no backend: every byte the app renders is a static
// JSON file under `data/`, emitted by platform/build/build_site_data.py. `base: "./"` keeps every
// emitted asset URL relative, so the same bundle works at the CloudFront root and under a
// `v/<stamp>/` prefix without a rebuild.
//
// NO ENVIRONMENT VARIABLES ARE READ HERE, DELIBERATELY. A Vite `define`/`import.meta.env` value is
// inlined into the bundle as a literal, which is the likeliest way an account id or a Cognito
// domain would end up in a published artifact. Anything the app needs to know at runtime is fetched
// from `data/`, where `gate_payload.py` scans it like every other byte.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Fail the build rather than silently shipping a bundle nobody expected to be large.
    chunkSizeWarningLimit: 700,
    sourcemap: false,
  },
});
