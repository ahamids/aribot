#!/usr/bin/env node
// Writes the current git short SHA to .env.production.local so
// `next build` bakes it into the bundle as NEXT_PUBLIC_BUILD_ID.
//
// Used by the Settings page "About" footer per design-pkg/screens-main.jsx:201-203.
// Falls back to a timestamp if the working tree isn't a git checkout
// (CI restores via tarball, vendor builds, etc.) so the bundle always
// has *something* identifying.
import { execSync } from "node:child_process";
import { writeFileSync, existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const target = resolve(root, ".env.production.local");

function gitShortSha() {
  try {
    return execSync("git rev-parse --short HEAD", {
      cwd: root,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return null;
  }
}

const sha = gitShortSha();
const buildId = sha ?? `ts-${Date.now().toString(36)}`;

// Preserve any other vars an operator may have placed in
// .env.production.local — only replace NEXT_PUBLIC_BUILD_ID.
let existing = "";
if (existsSync(target)) {
  existing = readFileSync(target, "utf8")
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith("NEXT_PUBLIC_BUILD_ID="))
    .join("\n");
  if (existing && !existing.endsWith("\n")) existing += "\n";
}

writeFileSync(target, `${existing}NEXT_PUBLIC_BUILD_ID=${buildId}\n`, "utf8");
console.log(`[write-build-id] NEXT_PUBLIC_BUILD_ID=${buildId}`);
