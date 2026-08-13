#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const localTsc = join(root, 'node_modules/.bin', process.platform === 'win32' ? 'tsc.cmd' : 'tsc');
const tsc = existsSync(localTsc) ? localTsc : process.platform === 'win32' ? 'tsc.cmd' : 'tsc';

process.env.AUDIOINTERVIEW_ROOT = root;

const result = spawnSync(tsc, ['-p', 'tsconfig.terminal.json'], {
  cwd: root,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

await import(pathToFileURL(join(root, '.terminal-interview-build/scripts/terminal-interview.js')).href);
