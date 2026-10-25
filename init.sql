-- Simulador de la tabla KNA1 (Maestro de Clientes SAP)
CREATE TABLE sap_clientes_kna1 (
    kunnr VARCHAR(10) PRIMARY KEY,     -- Número de cliente
    name1 VARCHAR(35),                 -- Nombre
    ort01 VARCHAR(35),                 -- Ciudad
    land1 VARCHAR(3),                  -- País
    spras VARCHAR(2),                  -- Idioma (ej. EN, PT, ES)
    ts_ms TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp origen
);

-- CRÍTICO PARA EL CDC: Permite a Debezium capturar el payload completo en Updates y Deletes
ALTER TABLE sap_clientes_kna1 REPLICA IDENTITY FULL;

-- Inserción de un registro de prueba inicial
INSERT INTO sap_clientes_kna1 (kunnr, name1, ort01, land1, spras) 
VALUES ('1000000001', 'Minera Australia Corp', 'Perth', 'AU', 'EN');
