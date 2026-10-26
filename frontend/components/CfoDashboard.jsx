"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import { ArrowLeft } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function CfoDashboard() {
  const [mpmData, setMpmData] = useState([]);
  const [abcData, setAbcData] = useState([]);
  const [selectedMpm, setSelectedMpm] = useState(null);
  const [selectedAbc, setSelectedAbc] = useState(null);

  useEffect(() => {
    axios.get(`${API_BASE}/api/mpm`).then((res) => setMpmData(res.data));
    axios.get(`${API_BASE}/api/abc-costs`).then((res) => setAbcData(res.data));
  }, []);

  const dimensionSummary = useMemo(() => {
    const totals = {};
    for (const row of abcData) {
      const key = row.DIMENSION_DRIVER;
      totals[key] = (totals[key] || 0) + row.COSTO_ASIGNADO_AL_OBJETO;
    }
    return Object.entries(totals).map(([dimension_driver, costo_total]) => ({
      dimension_driver,
      costo_total,
    }));
  }, [abcData]);

  const rootCauseRows = useMemo(
    () =>
      selectedAbc
        ? abcData.filter((row) => row.DIMENSION_DRIVER === selectedAbc)
        : [],
    [abcData, selectedAbc],
  );

  const showLevel2 = selectedMpm !== null && selectedMpm.includes("Costos WMS");

  function handleMpmClick(chartEvent) {
    const label =
      chartEvent?.activePayload?.[0]?.payload?.Concepto ??
      chartEvent?.activeLabel;
    if (label) {
      setSelectedMpm(label);
    }
  }

  function handleAbcClick(chartEvent) {
    const label =
      chartEvent?.activePayload?.[0]?.payload?.dimension_driver ??
      chartEvent?.activeLabel;
    if (label) {
      setSelectedAbc(label);
    }
  }

  function resetFiltros() {
    setSelectedMpm(null);
    setSelectedAbc(null);
  }

  return (
    <main style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <h1>CFO: Rentabilidad ABC &amp; IFRS 18</h1>

      {(selectedMpm || selectedAbc) && (
        <button onClick={resetFiltros} style={{ marginBottom: 16 }}>
          <ArrowLeft size={14} /> Resetear Filtros
        </button>
      )}

      <section style={{ marginBottom: 32 }} data-testid="level1-section">
        <h2>Nivel 1: Puente MPM</h2>
        <div data-testid="level1-chart">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={mpmData} onClick={handleMpmClick}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="Concepto" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="Monto" fill="#2563eb" cursor="pointer" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {showLevel2 && (
        <section style={{ marginBottom: 32 }} data-testid="level2-section">
          <h2>Nivel 2: Dimensiones ABC ({selectedMpm})</h2>
          <div data-testid="level2-chart">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={dimensionSummary}
                layout="vertical"
                onClick={handleAbcClick}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="dimension_driver" width={140} />
                <Tooltip />
                <Bar dataKey="costo_total" fill="#16a34a" cursor="pointer" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {selectedAbc && (
        <section data-testid="level3-section">
          <h2>Nivel 3: Causa Raiz Operativa ({selectedAbc})</h2>
          <table data-testid="level3-table">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>CEDI</th>
                <th>Descripcion Recurso</th>
                <th>Cantidad Consumida</th>
                <th>Costo Asignado</th>
              </tr>
            </thead>
            <tbody>
              {rootCauseRows.map((row, index) => (
                <tr key={`${row.centro_costo_origen}-${row.fecha}-${index}`}>
                  <td>{row.fecha}</td>
                  <td>{row.centro_costo_origen}</td>
                  <td>{row.DESCRIPCION_RECURSO}</td>
                  <td>{row.cantidad_consumida}</td>
                  <td>{row.COSTO_ASIGNADO_AL_OBJETO}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
