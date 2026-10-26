import { test, expect, Locator } from "@playwright/test";

async function clickChartCategory(
  chart: Locator,
  tick: Locator,
  axis: "x" | "y",
) {
  const chartBox = await chart.boundingBox();
  const tickBox = await tick.boundingBox();
  if (!chartBox || !tickBox) {
    throw new Error("No se pudo calcular la posicion del tick del eje");
  }
  const x =
    axis === "x" ? tickBox.x + tickBox.width / 2 : chartBox.x + chartBox.width / 2;
  const y =
    axis === "x" ? chartBox.y + chartBox.height / 2 : tickBox.y + tickBox.height / 2;
  await chart.page().mouse.click(x, y);
}

test("drill-down de 3 niveles: Puente MPM -> Dimensiones ABC -> Causa Raiz", async ({
  page,
}) => {
  await page.goto("/");

  // ---- Nivel 1: Puente MPM ----
  const level1Chart = page.getByTestId("level1-chart");
  await expect(level1Chart).toBeVisible();

  const mpmTick = level1Chart
    .locator(".recharts-xAxis .recharts-cartesian-axis-tick")
    .filter({ hasText: "2_(-) Costos WMS" });
  await expect(mpmTick).toBeVisible();

  await clickChartCategory(level1Chart, mpmTick, "x");

  // ---- Nivel 2: Dimensiones ABC ----
  const level2Section = page.getByTestId("level2-section");
  await expect(level2Section).toBeVisible();

  const level2Chart = page.getByTestId("level2-chart");
  const abcTick = level2Chart
    .locator(".recharts-yAxis .recharts-cartesian-axis-tick")
    .filter({ hasText: "3_MOVIMIENTO_TRANS" });
  await expect(abcTick).toBeVisible();

  await clickChartCategory(level2Chart, abcTick, "y");

  // ---- Nivel 3: Tabla de Causa Raiz ----
  const level3Section = page.getByTestId("level3-section");
  await expect(level3Section).toBeVisible();

  const rows = page.getByTestId("level3-table").locator("tbody tr");
  await expect(rows).not.toHaveCount(0);
  await expect(rows.first()).toBeVisible();
  await expect(level3Section).toContainText(
    "Depreciacion y Mantenimiento Montacargas",
  );
});
