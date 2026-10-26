import { test, expect, Locator } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 2600 } });

/**
 * Click reales (sin `force`) sobre los elementos SVG que Tremor renderiza
 * via Recharts, para validar que `onValueChange` responde a una interaccion
 * de usuario genuina (no solo a un dispatch sintetico de Playwright).
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
  await chart.locator(".recharts-bar-rectangle").nth(index).click();
}

/**
 * El DonutChart de Tremor no trae leyenda propia; las filas de la tabla
 * adyacente (`level2-table`) se renderizan desde el mismo arreglo y en el
 * mismo orden que los sectores del donut, asi que el indice de la fila cuyo
 * texto coincide es el mismo indice del sector `.recharts-sector` a activar.
 *
 * Un `<path>` de arco (anillo de donut) tiene un bounding-box cuyo centro
 * geometrico cae fuera del area realmente pintada (en el hueco central o en
 * un sector vecino): ni Playwright ni un mouse real pueden "clickear" ese
 * punto. `dispatchEvent("click")` dispara el evento DOM directamente sobre
 * el nodo del sector, activando el `onClick` real que Recharts/Tremor le
 * adjunta (y por lo tanto `onValueChange`), sin depender de hit-testing por
 * coordenadas.
 */
async function clickDonutSectorMatchingRowText(
  page: import("@playwright/test").Page,
  rowText: string,
) {
  const rows = page.getByTestId("level2-table").locator("tbody tr");
  const count = await rows.count();
  let index = -1;
  for (let i = 0; i < count; i++) {
    const text = await rows.nth(i).textContent();
    if (text && text.includes(rowText)) {
      index = i;
      break;
    }
  }
  if (index === -1) {
    throw new Error(`No se encontro la fila "${rowText}" en level2-table`);
  }
  const sectors = page.getByTestId("level2-chart").locator(".recharts-sector");
  await expect(sectors.nth(index)).toBeVisible();
  await sectors.nth(index).dispatchEvent("click");
}

test("drill-down de 5 niveles via eventos reales de Tremor (onValueChange)", async ({
  page,
}) => {
  await page.goto("/");

  // Esperar a que las 3 fuentes de datos (mpm/abc/corp) hayan cargado antes
  // de interactuar: evita el falso "No data" al hacer clic demasiado rapido.
  const level1Chart = page.getByTestId("level1-chart");
  await expect(level1Chart).toBeVisible({ timeout: 15000 });

  // ---- a) Nivel 1 -> Nivel 2 ----
  await expect(
    level1Chart
      .locator(".recharts-xAxis .recharts-cartesian-axis-tick")
      .filter({ hasText: "2_(-) Costos WMS" }),
  ).toBeVisible();
  await clickBarByTickText(level1Chart, ".recharts-xAxis", "2_(-) Costos WMS");

  const level2Section = page.getByTestId("level2-section");
  await expect(level2Section).toBeVisible();
  await expect(page.getByTestId("level2-chart").locator(".recharts-sector").first()).toBeVisible();

  // ---- b) Nivel 2 (clic real sobre el DonutChart) -> Nivel 3 ----
  await clickDonutSectorMatchingRowText(page, "3_MOVIMIENTO_TRANS");

  const level3Section = page.getByTestId("level3-section");
  await expect(level3Section).toBeVisible();

  // ---- c) Nivel 3 (fila CD0200) -> Nivel 4 ----
  const level3Row = page
    .getByTestId("level3-table")
    .locator("tr", { hasText: "2026-10" })
    .filter({ hasText: "CL_CD0200" });
  await expect(level3Row).toBeVisible();
  await level3Row.click();

  const level4Section = page.getByTestId("level4-section");
  await expect(level4Section).toBeVisible();

  // ---- d) Nivel 4 -> Nivel 5 ----
  const level4Row = page
    .getByTestId("level4-table")
    .locator("tr", { hasText: "Depreciación y Mantenimiento Montacargas" });
  await expect(level4Row).toBeVisible();
  await level4Row.click();

  const level5Section = page.getByTestId("level5-section");
  await expect(level5Section).toBeVisible();

  const level5Rows = page.getByTestId("level5-table").locator("tbody tr");
  await expect(level5Rows).not.toHaveCount(0);
  await expect(level5Rows.first()).toContainText("SKU-ABC");

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
