import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';

const cssBuild = spawnSync(process.execPath, [
  'node_modules/@tailwindcss/cli/dist/index.mjs',
  '-i', 'src/styles/globals.css',
  '-o', 'dist/ai-agent.css',
  '--minify',
], { stdio: 'inherit' });

if (cssBuild.status !== 0) {
  throw new Error('Tailwind CSS build failed');
}

await build({
  entryPoints: ['src/index.tsx'], bundle: true, minify: true, jsx: 'automatic',
  outfile: 'dist/ai-agent.js', define: { 'process.env.NODE_ENV': '"production"' },
});
