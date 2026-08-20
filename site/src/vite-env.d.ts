/// <reference types="vite/client" />

// Present only so TypeScript knows a side-effect CSS import is legal. It deliberately does NOT pull in
// `ImportMetaEnv` augmentations: nothing in this app reads an environment variable, because a build-time
// env var is how an account id or a resource ARN gets baked into a bundle that the payload gate then has
// to catch. The bundle is configuration-free, so there is nothing in it to leak.
