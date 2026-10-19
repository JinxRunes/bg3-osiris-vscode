import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';

await mkdir('lib', { recursive: true });
await build({
  entryPoints: { client: 'src/bg3/client.ts', server: 'src/bg3/server.ts', language: 'src/bg3/language.ts' },
  bundle: true, platform: 'node', target: 'node18', format: 'cjs', outdir: 'lib',
  external: ['vscode'], sourcemap: true, logLevel: 'info'
});
