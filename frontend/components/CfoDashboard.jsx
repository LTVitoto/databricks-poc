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
      const key = row.dimension_driver;
      totals[key] = (totals[key] || 0) + row.costo_asignado_linea;
    }
    return Object.entries(totals).map(([dimension_driver, costo_total]) => ({
      dimension_driver,
      costo_total,
    }));
  }, [abcData]);

  const rootCauseRows = useMemo(
    () =>
      selectedAbc
        ? abcData.filter((row) => row.dimension_driver === selectedAbc)
        : [],
    [abcData, selectedAbc],
  );

  const showLevel2 = selectedMpm !== null && selectedMpm.includes("Costos WMS");

  function handleMpmClick(chartEvent) {
    if (chartEvent && chartEvent.activeLabel) {
      setSelectedMpm(chartEvent.activeLabel);
    }
  }

  function handleAbcClick(chartEvent) {
    if (chartEvent && chartEvent.activeLabel) {
      setSelectedAbc(chartEvent.activeLabel);
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

      <section style={{ marginBottom: 32 }}>
        <h2>Nivel 1: Puente MPM</h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={mpmData} onClick={handleMpmClick}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="concepto" tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            <Bar dataKey="monto" fill="#2563eb" cursor="pointer" />
          </BarChart>
        </ResponsiveContainer>
      </section>

      {showLevel2 && (
        <section style={{ marginBottom: 32 }}>
          <h2>Nivel 2: Dimensiones ABC ({selectedMpm})</h2>
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
        </section>
      )}

      {selectedAbc && (
        <section>
          <h2>Nivel 3: Causa Raiz Operativa ({selectedAbc})</h2>
          <table>
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
              {rootCauseRows.map((row) => (
                <tr key={row.wms_telemetry_id}>
                  <td>{row.fecha}</td>
                  <td>{row.centro_costo_origen}</td>
                  <td>{row.descripcion_recurso}</td>
                  <td>{row.cantidad_consumida}</td>
                  <td>{row.costo_asignado_linea}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
