#!/usr/bin/env node
// Next.js `output: 'standalone'` does NOT copy .next/static or public/
// into the standalone tree. The standalone server then 404s on every
// chunk URL and every public file (favicon, site.webmanifest, ...),
// which manifests as "This page couldn't load" in the browser the
// moment client hydration tries to fetch a new content-hashed chunk.
//
// This script does the post-build copy that the Next.js docs say to
// "manually" perform. Lives in package.json's build script so plain
// `npm run build` always produces a deployable artifact.
import { existsSync, rmSync, cpSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const standalone = resolve(root, ".next/standalone");

if (!existsSync(standalone)) {
  console.error("[copy-standalone-assets] .next/standalone not found — is output: 'standalone' set in next.config?");
  process.exit(1);
}

const ops = [
  { from: resolve(root, ".next/static"), to: resolve(standalone, ".next/static") },
  { from: resolve(root, "public"), to: resolve(standalone, "public") },
];

for (const { from, to } of ops) {
  if (!existsSync(from)) {
    console.log(`[copy-standalone-assets] skipping (no source): ${from}`);
    continue;
  }
  rmSync(to, { recursive: true, force: true });
  cpSync(from, to, { recursive: true });
  console.log(`[copy-standalone-assets] copied ${from.replace(root + "/", "").replace(root + "\\", "")} -> standalone`);
}
