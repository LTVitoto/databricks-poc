"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  Card,
  Title,
  Subtitle,
  Text,
  Flex,
  Grid,
  BarChart,
  DonutChart,
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  BadgeDelta,
  Button,
} from "@tremor/react";
import { ArrowLeft } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const totalFormatter = new Intl.NumberFormat("es-CL", {
  maximumFractionDigits: 0,
});
const unitFormatter = new Intl.NumberFormat("es-CL", {
  maximumFractionDigits: 2,
});

function money(value) {
  return `$${totalFormatter.format(value ?? 0)}`;
}

function unit(value) {
  return value == null ? "-" : unitFormatter.format(value);
}

function groupSum(rows, keyFn, amountFn) {
  const map = new Map();
  for (const row of rows) {
    const key = keyFn(row);
    const entry = map.get(key) ?? { key, total: 0, rows: [] };
    entry.total += amountFn(row) ?? 0;
    entry.rows.push(row);
    map.set(key, entry);
  }
  return Array.from(map.values());
}

const BRANCH_WMS = "WMS";
const BRANCH_CORP = "CORP";
const DONUT_COLORS = ["blue", "cyan", "indigo", "violet", "fuchsia"];

export default function CfoDashboard() {
  const [mpmData, setMpmData] = useState([]);
  const [abcData, setAbcData] = useState([]);
  const [corpData, setCorpData] = useState([]);

  const [branch, setBranch] = useState(null);
  const [level2Key, setLevel2Key] = useState(null);
  const [level3Key, setLevel3Key] = useState(null);
  const [level4Key, setLevel4Key] = useState(null);

  useEffect(() => {
    axios.get(`${API_BASE}/api/mpm`).then((res) => setMpmData(res.data));
    axios.get(`${API_BASE}/api/abc-costs`).then((res) => setAbcData(res.data));
    axios
      .get(`${API_BASE}/api/corporate-costs`)
      .then((res) => setCorpData(res.data));
  }, []);

  const resultadoOperacional =
    mpmData.find((r) => r.Concepto?.includes("Resultado Operacional"))
      ?.Monto ?? 0;
  const ebitdaAjustado =
    mpmData.find((r) => r.Concepto?.includes("EBITDA Ajustado"))?.Monto ?? 0;
  const deltaPct =
    resultadoOperacional !== 0
      ? ((ebitdaAjustado - resultadoOperacional) /
          Math.abs(resultadoOperacional)) *
        100
      : 0;

  function clearDownstreamOfLevel1() {
    setLevel2Key(null);
    setLevel3Key(null);
    setLevel4Key(null);
  }

  function clearDownstreamOfLevel2() {
    setLevel3Key(null);
    setLevel4Key(null);
  }

  function clearDownstreamOfLevel3() {
    setLevel4Key(null);
  }

  function handleMpmClick(dataPoint) {
    clearDownstreamOfLevel1();
    const concepto = dataPoint?.Concepto;
    if (typeof concepto === "string" && concepto.includes("Costos WMS")) {
      setBranch(BRANCH_WMS);
    } else if (
      typeof concepto === "string" &&
      concepto.includes("Costos Corporativos")
    ) {
      setBranch(BRANCH_CORP);
    } else {
      setBranch(null);
    }
  }

  const branchRows =
    branch === BRANCH_WMS ? abcData : branch === BRANCH_CORP ? corpData : [];

  const level2Groups = useMemo(() => {
    if (branch === BRANCH_WMS) {
      return groupSum(
        branchRows,
        (r) => r.DIMENSION_DRIVER,
        (r) => r.COSTO_ASIGNADO_AL_OBJETO,
      );
    }
    if (branch === BRANCH_CORP) {
      return groupSum(
        branchRows,
        (r) => r.DESCRIPCION_RECURSO,
        (r) => r.COSTO_ASIGNADO_AL_OBJETO,
      );
    }
    return [];
  }, [branch, branchRows]);

  function handleLevel2RowClick(key) {
    clearDownstreamOfLevel2();
    setLevel2Key(key);
  }

  const level2FilteredRows = useMemo(() => {
    if (!level2Key) return [];
    const field =
      branch === BRANCH_WMS ? "DIMENSION_DRIVER" : "DESCRIPCION_RECURSO";
    return branchRows.filter((r) => r[field] === level2Key);
  }, [branch, branchRows, level2Key]);

  const level3Groups = useMemo(() => {
    return groupSum(
      level2FilteredRows,
      (r) => `${r.periodo_mes}__${r.centro_costo_origen}`,
      (r) => r.COSTO_ASIGNADO_AL_OBJETO,
    ).map((g) => {
      const [periodoMes, cedi] = g.key.split("__");
      return { ...g, periodoMes, cedi };
    });
  }, [level2FilteredRows]);

  function handleLevel3RowClick(periodoMes, cedi) {
    clearDownstreamOfLevel3();
    setLevel3Key({ periodoMes, cedi });
  }

  const level3FilteredRows = useMemo(() => {
    if (!level3Key) return [];
    return level2FilteredRows.filter(
      (r) =>
        r.periodo_mes === level3Key.periodoMes &&
        r.centro_costo_origen === level3Key.cedi,
    );
  }, [level2FilteredRows, level3Key]);

  const level4Groups = useMemo(() => {
    return groupSum(
      level3FilteredRows,
      (r) => r.DESCRIPCION_RECURSO,
      (r) => r.COSTO_ASIGNADO_AL_OBJETO,
    );
  }, [level3FilteredRows]);

  function handleLevel4RowClick(descripcionRecurso) {
    setLevel4Key(descripcionRecurso);
  }

  const level5Rows = useMemo(() => {
    if (!level4Key) return [];
    return level3FilteredRows.filter(
      (r) => r.DESCRIPCION_RECURSO === level4Key,
    );
  }, [level3FilteredRows, level4Key]);

  function resetAll() {
    setBranch(null);
    clearDownstreamOfLevel1();
  }

  const branchLabel =
    branch === BRANCH_WMS
      ? "Costos WMS"
      : branch === BRANCH_CORP
        ? "Costos Corporativos"
        : "";

  const anyDrillDownActive = branch || level2Key || level3Key || level4Key;

  return (
    <main className="max-w-5xl mx-auto p-6 space-y-6">
      <Flex justifyContent="between" alignItems="center">
        <div>
          <Title>CFO: Rentabilidad ABC &amp; IFRS 18</Title>
          <Subtitle>
            Puente MPM con drill-down operativo de 5 niveles
          </Subtitle>
        </div>
        {anyDrillDownActive && (
          <Button icon={ArrowLeft} variant="secondary" onClick={resetAll}>
            Resetear Filtros
          </Button>
        )}
      </Flex>

      <div data-testid="level1-section">
        <Card>
          <Flex justifyContent="between" alignItems="center">
            <Title>Nivel 1: Puente MPM</Title>
            <BadgeDelta deltaType={deltaPct >= 0 ? "increase" : "decrease"}>
              {`${unit(deltaPct)}% EBITDA Ajustado vs. Resultado Operacional`}
            </BadgeDelta>
          </Flex>
          <Text className="mt-1">Montos en USD (moneda grupo)</Text>
          <div data-testid="level1-chart">
            <BarChart
              className="mt-6"
              data={mpmData}
              index="Concepto"
              categories={["Monto"]}
              colors={["blue"]}
              valueFormatter={money}
              onValueChange={handleMpmClick}
              showLegend={false}
              intervalType={0}
              yAxisWidth={90}
              rotateLabelX={{ angle: -15, verticalShift: 10, xAxisHeight: 50 }}
            />
          </div>
        </Card>
      </div>

      {branch && (
        <div data-testid="level2-section">
          <Card>
            <Title>Nivel 2: Dimensiones de {branchLabel}</Title>
            <Text className="mt-1">Montos en CLP nominal</Text>
            <Grid numItemsSm={1} numItemsLg={2} className="gap-4 mt-4">
              <div data-testid="level2-chart">
                <DonutChart
                  data={level2Groups}
                  category="total"
                  index="key"
                  valueFormatter={money}
                  colors={DONUT_COLORS}
                />
              </div>
              <div data-testid="level2-table">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeaderCell>Dimension</TableHeaderCell>
                      <TableHeaderCell className="text-right">
                        Costo Total
                      </TableHeaderCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {level2Groups.map((g) => (
                      <TableRow
                        key={g.key}
                        className={`cursor-pointer hover:bg-tremor-background-muted ${
                          level2Key === g.key
                            ? "bg-tremor-background-muted"
                            : ""
                        }`}
                        onClick={() => handleLevel2RowClick(g.key)}
                      >
                        <TableCell>{g.key}</TableCell>
                        <TableCell className="text-right">
                          {money(g.total)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Grid>
          </Card>
        </div>
      )}

      {level2Key && (
        <div data-testid="level3-section">
          <Card>
            <Title>Nivel 3: Agrupacion Tactica ({level2Key})</Title>
            <div data-testid="level3-table">
              <Table className="mt-4">
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Periodo</TableHeaderCell>
                    <TableHeaderCell>CEDI</TableHeaderCell>
                    <TableHeaderCell className="text-right">
                      Costo Total
                    </TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {level3Groups.map((g) => (
                    <TableRow
                      key={g.key}
                      className="cursor-pointer hover:bg-tremor-background-muted"
                      onClick={() =>
                        handleLevel3RowClick(g.periodoMes, g.cedi)
                      }
                    >
                      <TableCell>{g.periodoMes}</TableCell>
                      <TableCell>{g.cedi}</TableCell>
                      <TableCell className="text-right">
                        {money(g.total)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </div>
      )}

      {level3Key && (
        <div data-testid="level4-section">
          <Card>
            <Title>
              Nivel 4: Recurso ({level3Key.periodoMes} - {level3Key.cedi})
            </Title>
            <div data-testid="level4-table">
              <Table className="mt-4">
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Recurso</TableHeaderCell>
                    <TableHeaderCell className="text-right">
                      Costo Total
                    </TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {level4Groups.map((g) => (
                    <TableRow
                      key={g.key}
                      className="cursor-pointer hover:bg-tremor-background-muted"
                      onClick={() => handleLevel4RowClick(g.key)}
                    >
                      <TableCell>{g.key}</TableCell>
                      <TableCell className="text-right">
                        {money(g.total)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </div>
      )}

      {level4Key && (
        <div data-testid="level5-section">
          <Card>
            <Title>Nivel 5: Detalle Transaccional ({level4Key})</Title>
            <div data-testid="level5-table">
              <Table className="mt-4">
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Fecha</TableHeaderCell>
                    <TableHeaderCell>SKU</TableHeaderCell>
                    <TableHeaderCell>Pedido</TableHeaderCell>
                    <TableHeaderCell className="text-right">
                      Cantidad Consumida
                    </TableHeaderCell>
                    <TableHeaderCell className="text-right">
                      Costo Asignado
                    </TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {level5Rows.map((row, index) => (
                    <TableRow
                      key={`${row.sku ?? row.DESCRIPCION_RECURSO}-${row.fecha ?? row.periodo_mes}-${index}`}
                    >
                      <TableCell>{row.fecha ?? "-"}</TableCell>
                      <TableCell>{row.sku ?? "-"}</TableCell>
                      <TableCell>{row.pedido ?? "-"}</TableCell>
                      <TableCell className="text-right">
                        {unit(row.cantidad_consumida)}
                      </TableCell>
                      <TableCell className="text-right">
                        {money(row.COSTO_ASIGNADO_AL_OBJETO)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </div>
      )}
    </main>
  );
}
