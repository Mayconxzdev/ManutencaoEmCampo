/**
 * Generates README images from the isolated synthetic demo.
 *
 * It starts the local e2e server, whose database is recreated under
 * .e2e_data, and stores only presentation images in docs/imagens.
 */
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '..');
const projectRoot = path.resolve(frontendRoot, '..');
const outputDir = path.join(projectRoot, 'docs', 'imagens');
const python = process.platform === 'win32'
  ? path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(projectRoot, '.venv', 'bin', 'python');
const serverScript = path.join(projectRoot, 'scripts', 'e2e_server.py');
const baseUrl = 'http://127.0.0.1:8124';

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForHealth() {
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await sleep(500);
  }
  throw new Error(`A demonstração não iniciou: ${lastError?.message || 'sem resposta em /health'}`);
}

async function selectReviewer(page) {
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /Camila Duarte/ }).click();
  await page.getByRole('heading', { name: 'Hoje na Produção' }).waitFor();
  await page.getByText('MEC-101', { exact: false }).waitFor();
}

async function capture(page, route, heading, filename) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: heading }).waitFor();
  await page.screenshot({ path: path.join(outputDir, filename), fullPage: true });
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const server = spawn(python, [serverScript], {
    cwd: projectRoot,
    stdio: 'inherit',
    windowsHide: true,
  });

  try {
    await waitForHealth();
    const browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await selectReviewer(page);
    await page.screenshot({ path: path.join(outputDir, '01-painel-operacional.png'), fullPage: true });
    await capture(page, '/ativos', /Máquinas e Equipamentos/, '02-ativos-e-identificacao.png');
    await capture(page, '/checklists/iniciar', /Iniciar Checklist Digital/, '03-checklist-por-ativo.png');
    await capture(page, '/historico', /Histórico/, '04-historico.png');
    await browser.close();
  } finally {
    server.kill();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
