// Not runnable in this repository yet: Playwright is intentionally not installed.
// Set E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD in a local environment, install
// Playwright externally, and remove this guard to exercise a local Superset stack.
import { test, expect } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:8089';
const username = process.env.E2E_ADMIN_USERNAME;
const password = process.env.E2E_ADMIN_PASSWORD;
const datasetId = process.env.E2E_DATASET_ID;
const metricId = process.env.E2E_METRIC_ID;
const apiPrefix = '/extensions/text-to-bi/superset-semantic-layer/semantic-layer';

test.describe('metric contract lifecycle (local stack)', () => {
  test.skip(!username || !password || !datasetId || !metricId, 'Requires explicitly configured local test credentials and IDs.');

  test('admin creates, approves, executes, and revokes a saved metric contract', async ({ page }) => {
    await page.goto(`${baseURL}/login/`);
    await page.getByLabel(/username/i).fill(username!);
    await page.getByLabel(/password/i).fill(password!);
    await page.getByRole('button', { name: /sign in|login/i }).click();
    const csrf = await page.request.get(`${baseURL}/api/v1/security/csrf_token/`);
    const token = (await csrf.json()).result;
    const headers = { 'X-CSRFToken': token };
    const root = `${baseURL}${apiPrefix}/dataset/${datasetId}/metrics/${metricId}`;

    try {
      let candidate = await page.request.post(`${root}/contract/candidate`, { headers });
      if (candidate.status() === 409) {
        const revokeExisting = await page.request.post(`${root}/contract/revoke`, { headers });
        expect(revokeExisting.ok()).toBeTruthy();
        candidate = await page.request.post(`${root}/contract/candidate`, { headers });
      }
      expect(candidate.status()).toBe(201);
      const candidatePayload = await candidate.json();
      expect(candidatePayload).toMatchObject({
        contract: { dataset_id: Number(datasetId), metric_id: Number(metricId), status: 'candidate', current: false },
      });

      const approved = await page.request.post(`${root}/contract/approve`, { headers });
      expect(approved.status()).toBe(200);
      await expect(approved.json()).resolves.toMatchObject({
        contract: { dataset_id: Number(datasetId), metric_id: Number(metricId), status: 'approved', current: true },
      });

      const execution = await page.request.post(`${root}/semantic-query/execute`, {
        headers,
        data: { dimensions: [], filters: [] },
      });
      expect(execution.status()).toBe(200);
      const executionPayload = await execution.json();
      expect(executionPayload).toEqual(expect.objectContaining({
        columns: expect.any(Array),
        rows: expect.any(Array),
        row_count: expect.any(Number),
        truncated: expect.any(Boolean),
      }));
      expect(executionPayload.row_count).toBe(executionPayload.rows.length);

      const revoked = await page.request.post(`${root}/contract/revoke`, { headers });
      expect(revoked.status()).toBe(200);
      await expect(revoked.json()).resolves.toMatchObject({
        contract: { dataset_id: Number(datasetId), metric_id: Number(metricId), status: 'revoked', current: false },
      });
      const revokedExecution = await page.request.post(`${root}/semantic-query/execute`, {
        headers,
        data: { dimensions: [], filters: [] },
      });
      expect(revokedExecution.status()).toBe(403);
      await expect(revokedExecution.json()).resolves.toMatchObject({ message: expect.any(String) });
    } finally {
      await page.request.post(`${root}/contract/revoke`, { headers });
    }
  });
});
