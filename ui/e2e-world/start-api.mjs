// Starts a throwaway API server for the world-model end-to-end test: its own port, its own
// temporary data folder (machine config, registry), nothing from this machine.
// Playwright runs this as a webServer and stops it when the run ends.
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const port = process.env.WORLD_E2E_API_PORT ?? '4311';
// A folder named by the port, so the spec can find the runs root (data/asset-runs) to put a
// stand-in run in. It is emptied at start and removed at the end.
const root = join(tmpdir(), `world-e2e-api-${port}`);
rmSync(root, { recursive: true, force: true });
mkdirSync(root, { recursive: true });
const config = join(root, 'machine.json');
writeFileSync(config, JSON.stringify({ data_dir: join(root, 'data') }));

// The pipeline's own machine config for the run: the stand-in adapters only, with the tools interpreter (numpy, scipy,
// trimesh, Pillow, fast-simplification). That interpreter is GENSTAGE_TEST_TOOLS_PYTHON when set, else the
// `tools_python` of this computer's machine config (GENSTAGE_MACHINE_CONFIG, else ~/.config/generative-stage/machine.json,
// which ./install.sh writes). Nothing else of that config is used; the identity cache is kept in the scratch folder too.
const pipelineDir = resolve(import.meta.dirname, '..', '..', 'pipeline');
const toolsPython =
  process.env.GENSTAGE_TEST_TOOLS_PYTHON ||
  execFileSync('python3', ['-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import machine; print(machine.tools_python())', pipelineDir], { encoding: 'utf8' }).trim();
try {
  execFileSync(toolsPython, ['-I', '-c', 'import numpy, scipy, trimesh, PIL, fast_simplification']);
} catch {
  console.error(`start-api: the tools interpreter ${toolsPython} lacks pipeline/requirements.txt; run ./install.sh, or set GENSTAGE_TEST_TOOLS_PYTHON or the machine setting tools_python`);
  process.exit(1);
}
const pipelineConfig = join(root, 'pipeline-machine.json');
writeFileSync(pipelineConfig, JSON.stringify({ tools_python: toolsPython }));

const server = spawn(
  'uv',
  ['run', 'python', '-m', 'authoring.server', '--port', port],
  {
    cwd: resolve(import.meta.dirname, '..', '..', 'server'),
    env: { ...process.env, GENSTAGE_SERVER_CONFIG: config, GENSTAGE_MACHINE_CONFIG: pipelineConfig, GENSTAGE_IDENTITY_CACHE: join(root, 'identity.json') },
    stdio: 'inherit',
  },
);

function stop() {
  server.kill('SIGTERM');
}
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
server.on('exit', (code) => {
  rmSync(root, { recursive: true, force: true });
  process.exit(code ?? 0);
});
