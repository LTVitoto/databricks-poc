import { test, expect, Locator } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 2200 } });

/**
 * Localiza el indice del tick (por texto) dentro de un eje y hace clic en
 * la barra de Recharts que ocupa esa misma posicion (`.recharts-bar-rectangle`
 * respeta el orden de los datos, igual que los ticks del eje de categoria).
 */
async function clickBarByTickText(
  chart: Locator,
  axisSelector: string,
  tickText: string,
) {
  const ticks = chart.locator(`${axisSelector} .recharts-cartesian-axis-tick`);
  const count = await ticks.count();
  let index = -1;
  for (let i = 0; i < count; i++) {
    const text = await ticks.nth(i).textContent();
    if (text && text.includes(tickText)) {
      index = i;
      break;
    }
  }
  if (index === -1) {
    throw new Error(`No se encontro el tick "${tickText}"`);
  }
  await chart.locator(".recharts-bar-rectangle").nth(index).click({ force: true });
}

test("drill-down de 3 niveles: Puente MPM -> Dimensiones ABC -> Causa Raiz", async ({
  page,
}) => {
  await page.goto("/");

  // ---- Nivel 1: Puente MPM ----
  const level1Chart = page.getByTestId("level1-chart");
  await expect(level1Chart).toBeVisible();
  await expect(
    level1Chart
      .locator(".recharts-xAxis .recharts-cartesian-axis-tick")
      .filter({ hasText: "2_(-) Costos WMS" }),
  ).toBeVisible();

  await clickBarByTickText(level1Chart, ".recharts-xAxis", "2_(-) Costos WMS");

  // ---- Nivel 2: Dimensiones ABC ----
  const level2Section = page.getByTestId("level2-section");
  await expect(level2Section).toBeVisible();

  const level2Chart = page.getByTestId("level2-chart");
  await expect(
    level2Chart
      .locator(".recharts-yAxis .recharts-cartesian-axis-tick")
      .filter({ hasText: "3_MOVIMIENTO_TRANS" }),
  ).toBeVisible();

  await clickBarByTickText(level2Chart, ".recharts-yAxis", "3_MOVIMIENTO_TRANS");

  // ---- Nivel 3: Tabla de Causa Raiz ----
  const level3Section = page.getByTestId("level3-section");
  await expect(level3Section).toBeVisible();

  const rows = page.getByTestId("level3-table").locator("tbody tr");
  await expect(rows).not.toHaveCount(0);
  await expect(rows.first()).toBeVisible();
  await expect(level3Section).toContainText(
    "Depreciación y Mantenimiento Montacargas",
  );
});
