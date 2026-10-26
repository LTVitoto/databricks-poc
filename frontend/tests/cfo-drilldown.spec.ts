import { test, expect, Locator } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 2600 } });

/**
 * Localiza el indice del tick (por texto) dentro de un eje y hace clic en
 * la barra de Recharts que ocupa esa misma posicion (`.recharts-bar-rectangle`
 * respeta el orden de los datos, igual que los ticks del eje de categoria).
 * Tremor's BarChart sigue renderizando los mismos elementos de Recharts.
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

test("drill-down de 5 niveles: Puente MPM -> ... -> Transaccional, con limpieza de estados", async ({
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

  // ---- Nivel 2: Dimensiones ABC (tabla junto al DonutChart) ----
  const level2Section = page.getByTestId("level2-section");
  await expect(level2Section).toBeVisible();
  await expect(page.getByTestId("level2-chart")).toBeVisible();

  const level2Table = page.getByTestId("level2-table");
  const level2Row = level2Table.locator("tr", { hasText: "3_MOVIMIENTO_TRANS" });
  await expect(level2Row).toBeVisible();
  await level2Row.click();

  // ---- Nivel 3: Agrupacion Tactica (Periodo x CEDI) ----
  const level3Section = page.getByTestId("level3-section");
  await expect(level3Section).toBeVisible();

  const level3Table = page.getByTestId("level3-table");
  const level3Row = level3Table
    .locator("tr", { hasText: "2026-10" })
    .filter({ hasText: "CL_CD0100" });
  await expect(level3Row).toBeVisible();
  await level3Row.click();

  // ---- Nivel 4: Recurso ----
  const level4Section = page.getByTestId("level4-section");
  await expect(level4Section).toBeVisible();

  const level4Table = page.getByTestId("level4-table");
  const level4Row = level4Table.locator("tr", {
    hasText: "Depreciación y Mantenimiento Montacargas",
  });
  await expect(level4Row).toBeVisible();
  await level4Row.click();

  // ---- Nivel 5: Detalle Transaccional ----
  const level5Section = page.getByTestId("level5-section");
  await expect(level5Section).toBeVisible();

  const level5Rows = page.getByTestId("level5-table").locator("tbody tr");
  await expect(level5Rows).not.toHaveCount(0);
  const rowCount = await level5Rows.count();
  expect(rowCount).toBeGreaterThan(100);
  await expect(level5Rows.first()).toContainText("SKU-ABC");

  // Ningun numero crudo sin formato (regla de oro: Intl.NumberFormat en todos
  // los niveles, nunca 15 decimales sueltos como "111.20069444444444"). En
  // es-CL el separador decimal es "," (el "." es de miles), por eso se busca
  // una coma seguida de 3+ digitos, no un punto.
  await expect(level5Section).not.toContainText(/,\d{3,}/);

  // ---- Cascada estricta: clic en N1 (otra categoria) limpia N2-N5 ----
  await clickBarByTickText(
    level1Chart,
    ".recharts-xAxis",
    "1_Resultado Operacional",
  );

  await expect(level2Section).toHaveCount(0);
  await expect(level3Section).toHaveCount(0);
  await expect(level4Section).toHaveCount(0);
  await expect(level5Section).toHaveCount(0);
});
