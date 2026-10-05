# Filtro de ahorro comprobado — 4 de octubre de 2026

Estas reglas reemplazan los umbrales publicados de 60/80% para Rappi y hogar.
Autos, inmuebles, viajes y el lector separado de Tambo/Makro conservan sus reglas.

- **Hogar:** ahorro de al menos 15% y S/ 50 contra la mediana de precios observados
  en siete días distintos dentro de los últimos 30; debe haber una observación
  en los siete días anteriores. Se guarda el mínimo de cada día, nunca el tachado.
- **Rappi:** misma referencia, con mínimo de 20% y S/ 10 por producto/presentación.
  Local, identificador, nombre/presentación y condición Pro forman la identidad.
  Las sucursales se comparan por separado. No se calculan precios a partir de
  porcentajes para usarlos como evidencia ni se avisan anuncios sin producto.
- **Comparación actual de hogar:** solo títulos completos idénticos con código
  de modelo, misma categoría, moneda y condiciones. Dos vendedores independientes
  pueden aportar referencia cuando falta historial; se toma el menor precio.
  Un comparable actual más barato también limita la referencia histórica.
  Es una comparación de los catálogos observados, no de todo el mercado. No se
  presume equivalencia entre tamaños, modelos o nombres genéricos.
- **Cargos:** por elección del usuario, si la fuente pública no permite confirmar
  entrega/cargos para su dirección, se muestra el ahorro antes de cargos y
  «Envío/cargos por confirmar». No se anuncia ese importe como ahorro neto ni
  como total de compra. No se entra en cuentas ni carritos para obtenerlo.
- **Condiciones:** CMR queda fuera de alertas principales mientras no se confirme
  que el usuario puede utilizarla. Rappi Pro solo se admite con su configuración
  habilitada y se indica en el mensaje.
- **Volumen:** cinco productos como máximo por ronda en Rappi y por entrega de
  hogar. Hogar conserva el resumen cada tres horas y revisión cada 30 minutos.
  Una caída comprobada de 40% en hogar puede salir antes del resumen. El filtro
  no completa cupos con candidatos sin evidencia.
- **Repetición:** durante 30 días solo se vuelve a avisar una oferta si el precio
  mejora al menos 3% y S/ 1. No se marca una entrega fallida ni una oferta omitida.
  Los porcentajes anunciados y cambios de la referencia no son novedades.
- **Arranque:** Rappi empieza a reunir historial propio, incluso de productos sin
  descuento en los menús/páginas consultados. En hogar se reutiliza el historial
  observado existente. Sin evidencia suficiente no hay alerta; los motivos se
  contabilizan en registros y métricas, sin publicar información personal.
- **Cobertura y costo:** se mantienen los presupuestos de consultas y robots.
  Falabella/Sodimac ahora recorren las mismas categorías sin el filtro de 60%
  anunciado. VTEX sigue siendo una muestra de 50 productos por fuente. El filtro
  rápido precede a la revalidación; esta se detiene al confirmar cinco productos.
  No se garantiza detectar todo el catálogo ni comparar por kilo cuando no se
  dispone de cantidades estructuradas: se exige la misma presentación.

Implementación: `monitor/value.py`, integración en `main.py` y `catalogs.py`.
La cola antigua se vuelve a evaluar antes de enviar. Las reglas anteriores de
priorización permanecen como auxiliares de cola, pero no pueden eludir el filtro
de entrada y salida. Pruebas de regresión en `tests/test_value.py` y la suite.
