import { expect, test } from '@playwright/test';

async function selectDemoReviewer(page: import('@playwright/test').Page) {
  await page.goto('/');
  const camila = page.getByRole('button', { name: /Camila Duarte/ });
  await expect(camila).toBeVisible();
  await camila.click();
  await expect(page.getByRole('heading', { name: 'Hoje na Produção' })).toBeVisible();
}

test('apresenta o painel com dados sintéticos', async ({ page }) => {
  await selectDemoReviewer(page);

  await expect(page.getByRole('heading', { name: 'Hoje na Produção' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Atenções e tarefas de hoje/i })).toBeVisible();
  await expect(page.getByText('MEC-101', { exact: false })).toBeVisible();
});

test('lista os ativos e permite chegar ao checklist por ativo', async ({ page }) => {
  await selectDemoReviewer(page);

  await page.getByRole('button', { name: 'Máquinas e Equipamentos' }).click();
  await expect(page.getByRole('heading', { name: /Máquinas e Equipamentos/i })).toBeVisible();
  await expect(page.getByText('Prensa hidráulica de bancada')).toBeVisible();

  await page.goto('/checklists/iniciar');
  await expect(page.getByRole('heading', { name: /Iniciar Checklist Digital/i })).toBeVisible();
  await expect(page.getByText('Prensa hidráulica de bancada')).toBeVisible();
  await expect(page.getByText('MEC-101', { exact: false })).toBeVisible();
});

test('mantém uma navegação utilizável em cada viewport', async ({ page }) => {
  await selectDemoReviewer(page);

  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
});
