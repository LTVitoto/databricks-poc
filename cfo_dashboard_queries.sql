-- cfo_dashboard_queries.sql
-- Consultas listas para pegar en Databricks SQL Editor y usar en un Dashboard.
-- Tabla fuente: mi_test_catalogo.default.gold_acdoca_ifrs18 (ACDOCA x IFRS18_FSV_MAP,
-- gobernada con CHECK constraints en ifrs18_category y ksl).

-- ============================================================================
-- Consulta 1: Waterfall P&L IFRS 18 (consolidado, intercompany eliminado IFRS 10)
-- Visualizacion sugerida: Waterfall, eje X = categoria (orden por `orden`),
-- eje Y = resultado_ksl. Ultima barra ("Resultado Neto") como total.
-- ============================================================================
WITH consolidado AS (
    SELECT
        ifrs18_category,
        -SUM(ksl) AS resultado_ksl
    FROM mi_test_catalogo.default.gold_acdoca_ifrs18
    WHERE rassc IS NULL  -- IFRS 10: excluye lineas intercompany
    GROUP BY ifrs18_category
),
ordenado AS (
    SELECT
        ifrs18_category AS categoria,
        resultado_ksl,
        CASE ifrs18_category
            WHEN 'Operating' THEN 1
            WHEN 'Investing' THEN 2
            WHEN 'Financing' THEN 3
            WHEN 'Taxes'     THEN 4
        END AS orden
    FROM consolidado
)
SELECT categoria, resultado_ksl, orden FROM ordenado
UNION ALL
SELECT 'Resultado Neto' AS categoria, SUM(resultado_ksl) AS resultado_ksl, 5 AS orden
FROM ordenado
ORDER BY orden;

-- ============================================================================
-- Consulta 2: KPI EBITDA Ajustado (MPM, IFRS 18) comparativo por Segmento (IFRS 8)
-- Visualizacion sugerida: Tabla / Bar chart agrupado por sociedad.
-- ============================================================================
WITH operativo AS (
    SELECT
        rbukrs,
        -SUM(ksl) AS operating_profit_ksl,
        SUM(CASE WHEN mpm_tag = 'EBITDA_ADJUSTED' THEN ksl ELSE 0 END)
            AS depreciacion_addback_ksl
    FROM mi_test_catalogo.default.gold_acdoca_ifrs18
    WHERE rassc IS NULL                  -- IFRS 10: consolidado, sin intercompany
      AND ifrs18_category = 'Operating'  -- IFRS 18: solo categoria Operating
    GROUP BY rbukrs
)
SELECT
    rbukrs AS sociedad,
    operating_profit_ksl,
    depreciacion_addback_ksl,
    operating_profit_ksl + depreciacion_addback_ksl AS ebitda_ajustado_ksl
FROM operativo
ORDER BY rbukrs;

-- ============================================================================
-- Consulta 3: Detalle de impacto Intercompany (IFRS 10) por cuenta y sociedad
-- Visualizacion sugerida: Tabla detalle (drill-down del total eliminado).
-- ============================================================================
SELECT
    rbukrs       AS sociedad_origen,
    rassc        AS sociedad_contraparte,
    racct        AS cuenta,
    account_desc AS descripcion_cuenta,
    ifrs18_category,
    COUNT(*)     AS lineas_eliminadas,
    SUM(ksl)     AS ksl_eliminado
FROM mi_test_catalogo.default.gold_acdoca_ifrs18
WHERE rassc IS NOT NULL
GROUP BY rbukrs, rassc, racct, account_desc, ifrs18_category
ORDER BY sociedad_origen, cuenta;
