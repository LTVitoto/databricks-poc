"use client";
import React, { useState, useEffect, useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const formatUSD = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val);

const ChevronRight = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
    <path d="m9 18 6-6-6-6"/>
  </svg>
);

export default function EnterpriseCFO() {
  const [rawData, setRawData] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dim, setDim] = useState(null);
  const [cedi, setCedi] = useState(null);
  const [recurso, setRecurso] = useState(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/abc-costs')
      .then(res => res.json())
      .then(data => {
        const normalized = data.map(d => ({
          dimension: d.dimension_driver || d.DIMENSION_DRIVER,
          cedi: d.centro_costo_origen || d.CEDI || d.CENTRO_COSTO_ORIGEN,
          recurso: d.descripcion_recurso || d.DESCRIPCION_RECURSO,
          costo: Number(d.costo_asignado_al_objeto || d.COSTO_ASIGNADO_AL_OBJETO || d.costo_asignado || 0),
          cantidad: Number(d.cantidad_consumida || d.VOLUMEN_CONSUMIDO || 0),
          sku: d.sku || d.SKU,
          pedido: d.pedido || d.PEDIDO
        }));
        setRawData(normalized);
        setLoading(false);
      })
      .catch(e => {
        console.error("Error conectando a FastAPI:", e);
        setLoading(false);
      });
  }, []);

  const totalCost = useMemo(() => rawData.reduce((sum, item) => sum + item.costo, 0), [rawData]);

  const dims = useMemo(() => {
    const group = rawData.reduce((acc, curr) => {
      if (!curr.dimension) return acc;
      acc[curr.dimension] = (acc[curr.dimension] || 0) + curr.costo;
      return acc;
    }, {});
    return Object.entries(group).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  }, [rawData]);

  const cedis = useMemo(() => {
    if (!dim) return [];
    const group = rawData.filter(d => d.dimension === dim).reduce((acc, curr) => {
      acc[curr.cedi] = (acc[curr.cedi] || 0) + curr.costo;
      return acc;
    }, {});
    return Object.entries(group).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  }, [rawData, dim]);

  const recursos = useMemo(() => {
    if (!cedi) return [];
    const group = rawData.filter(d => d.dimension === dim && d.cedi === cedi).reduce((acc, curr) => {
      acc[curr.recurso] = (acc[curr.recurso] || 0) + curr.costo;
      return acc;
    }, {});
    return Object.entries(group).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  }, [rawData, dim, cedi]);

  const transacciones = useMemo(() => {
    if (!recurso) return [];
    return rawData.filter(d => d.dimension === dim && d.cedi === cedi && d.recurso === recurso);
  }, [rawData, dim, cedi, recurso]);

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mb-4"></div>
        <h2 className="text-xl font-semibold text-slate-700">Inicializando Motor Lakehouse...</h2>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 font-sans">
      <header className="bg-white border-b border-slate-200 px-8 py-6 shadow-sm flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Financial Intelligence Center</h1>
          <p className="text-sm text-slate-500 font-medium">Motor de Costeo ABC & IFRS 18</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-400 font-bold uppercase tracking-wider mb-1">Costo Logístico Total Analizado</p>
          <p className="text-3xl font-extrabold text-red-600">{formatUSD(totalCost)}</p>
        </div>
      </header>

      <main className="p-8 max-w-[1600px] mx-auto space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="col-span-1 lg:col-span-2 bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <h2 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-4">Distribución por Driver de Actividad</h2>
            <div className="h-64">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={dims} margin={{ left: 20 }}>
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} />
                  <YAxis tickFormatter={(v) => `$${v/1000}k`} axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} />
                  <Tooltip cursor={{fill: '#f1f5f9'}} formatter={(value) => formatUSD(value)} contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'}} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {dims.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={dim === entry.name ? '#4f46e5' : '#94a3b8'} className="transition-all duration-300"/>
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="col-span-1 bg-gradient-to-br from-indigo-900 to-slate-900 rounded-xl shadow-sm p-6 text-white flex flex-col justify-between">
            <div>
              <h2 className="text-indigo-200 font-medium text-sm tracking-wide uppercase mb-2">Estado del Pipeline</h2>
              <p className="text-2xl font-semibold">Databricks Serverless</p>
              <p className="text-sm text-indigo-300 mt-2">Catálogo: <span className="font-mono bg-indigo-950 px-2 py-1 rounded">mi_test_catalogo</span></p>
            </div>
            <div className="mt-8 border-t border-indigo-800 pt-6">
              <p className="text-indigo-200 text-sm mb-1">Volumen Transaccional Procesado</p>
              <p className="text-3xl font-bold">{new Intl.NumberFormat('en-US').format(rawData.length)} <span className="text-lg font-normal text-indigo-400">filas</span></p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="bg-slate-100 px-6 py-4 border-b border-slate-200 flex justify-between items-center">
            <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wider">Explorador de Causa Raíz (Drill-Down)</h2>
            <button
              onClick={() => { setDim(null); setCedi(null); setRecurso(null); }}
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              Resetear Filtros
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-slate-200 h-[400px]">
            <div className="overflow-y-auto bg-white">
              <div className="p-3 bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-500 uppercase sticky top-0">1. Dimensión WMS</div>
              <ul className="p-2 space-y-1">
                {dims.map((d) => (
                  <li key={d.name} onClick={() => { setDim(d.name); setCedi(null); setRecurso(null); }}
                      className={`flex justify-between items-center p-3 rounded cursor-pointer transition-colors ${dim === d.name ? 'bg-indigo-50 border border-indigo-200 shadow-sm' : 'hover:bg-slate-50 border border-transparent'}`}>
                    <span className={`font-medium ${dim === d.name ? 'text-indigo-700' : 'text-slate-700'}`}>{d.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-slate-500">{formatUSD(d.value)}</span>
                      {dim === d.name && <ChevronRight/>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <div className="overflow-y-auto bg-slate-50/50">
              <div className="p-3 bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-500 uppercase sticky top-0">2. Centro de Costo (CEDI)</div>
              {dim ? (
                <ul className="p-2 space-y-1">
                  {cedis.map((c) => (
                    <li key={c.name} onClick={() => { setCedi(c.name); setRecurso(null); }}
                        className={`flex justify-between items-center p-3 rounded cursor-pointer transition-colors ${cedi === c.name ? 'bg-indigo-50 border border-indigo-200 shadow-sm' : 'hover:bg-white border border-transparent shadow-sm'}`}>
                      <span className={`font-medium text-sm ${cedi === c.name ? 'text-indigo-700' : 'text-slate-700'}`}>{c.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-500">{formatUSD(c.value)}</span>
                        {cedi === c.name && <ChevronRight/>}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-slate-400">Selecciona una dimensión</div>
              )}
            </div>

            <div className="overflow-y-auto bg-slate-50/80">
              <div className="p-3 bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-500 uppercase sticky top-0">3. Recurso Operativo</div>
              {cedi ? (
                <ul className="p-2 space-y-1">
                  {recursos.map((r) => (
                    <li key={r.name} onClick={() => setRecurso(r.name)}
                        className={`flex justify-between items-center p-3 rounded cursor-pointer transition-colors ${recurso === r.name ? 'bg-indigo-600 text-white shadow-md' : 'hover:bg-white bg-white border border-slate-100 shadow-sm'}`}>
                      <span className={`font-medium text-sm truncate pr-2 ${recurso === r.name ? 'text-white' : 'text-slate-700'}`}>{r.name.replace(/_/g, ' ')}</span>
                      <span className={`text-xs font-bold whitespace-nowrap ${recurso === r.name ? 'text-indigo-100' : 'text-slate-500'}`}>{formatUSD(r.value)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-slate-400">Selecciona un CEDI</div>
              )}
            </div>
          </div>
        </div>

        {recurso && (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
             <div className="bg-slate-900 px-6 py-4 flex justify-between items-center">
                <h2 className="text-sm font-bold text-white uppercase tracking-wider">Auditoría Transaccional</h2>
                <span className="px-3 py-1 bg-slate-800 text-indigo-300 text-xs font-bold rounded-full border border-slate-700">
                  {transacciones.length} registros encontrados
                </span>
             </div>
             <div className="overflow-x-auto max-h-96">
                <table className="min-w-full divide-y divide-slate-200">
                  <thead className="bg-slate-50 sticky top-0 shadow-sm">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-bold text-slate-500 uppercase">SKU / Producto</th>
                      <th className="px-6 py-3 text-left text-xs font-bold text-slate-500 uppercase">Pedido / Order</th>
                      <th className="px-6 py-3 text-right text-xs font-bold text-slate-500 uppercase">Volumen Consumido</th>
                      <th className="px-6 py-3 text-right text-xs font-bold text-slate-500 uppercase">Impacto Asignado ($)</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-slate-100">
                    {transacciones.slice(0, 100).map((t, i) => (
                      <tr key={i} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-3 whitespace-nowrap text-sm font-medium text-slate-900">{t.sku}</td>
                        <td className="px-6 py-3 whitespace-nowrap text-sm text-slate-500">{t.pedido}</td>
                        <td className="px-6 py-3 whitespace-nowrap text-sm text-right text-slate-600">{t.cantidad.toFixed(2)}</td>
                        <td className="px-6 py-3 whitespace-nowrap text-sm text-right font-bold text-red-600">{formatUSD(t.costo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
             </div>
          </div>
        )}
      </main>
    </div>
  );
}
