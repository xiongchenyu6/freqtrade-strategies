#!/usr/bin/env node
/**
 * Build the Starlight docs app and copy its output into static/docs/.
 * Runs automatically in `pnpm build` so one deploy = app + docs.
 */
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DOCS_APP = join(__dirname, '..', '..', 'docs');
const DOCS_DIST = join(DOCS_APP, 'dist');
const DST = join(__dirname, '..', 'static', 'docs');

if (!existsSync(DOCS_APP)) {
	console.log('sync-starlight: no docs app, skipping');
	process.exit(0);
}

console.log('sync-starlight: building Starlight docs…');
// Use the same pnpm launcher that invoked us — on NixOS there is no global `pnpm`
// on PATH (corepack is used), so resolving by name fails. `npm_execpath` is the
// absolute path to the JS entry of the package manager (pnpm's own .cjs).
const pnpmLauncher = process.env.npm_execpath;
const r = pnpmLauncher
	? spawnSync(process.execPath, [pnpmLauncher, 'build'], {
			stdio: 'inherit',
			cwd: DOCS_APP,
			env: { ...process.env }
		})
	: spawnSync('pnpm', ['build'], { stdio: 'inherit', cwd: DOCS_APP, env: { ...process.env } });
if (r.status !== 0) {
	console.error('sync-starlight: starlight build failed');
	process.exit(r.status ?? 1);
}

rmSync(DST, { recursive: true, force: true });
mkdirSync(DST, { recursive: true });
cpSync(DOCS_DIST, DST, { recursive: true });
console.log(`sync-starlight: copied Starlight output → ${DST}`);
