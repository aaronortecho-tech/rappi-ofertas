# Factoring: solo evidencia completa

Implementado el 8 de octubre de 2026. Es un monitor de lectura y selección; no
abre cuentas, no deposita, no reserva y no invierte. No calcula probabilidades de
incumplimiento. Las reglas son una política conservadora inicial, no un modelo
validado con resultados de Prestamype.

## Acceso y estado inicial

Prestamype indica que las oportunidades requieren registro, validación y
activación de cuenta. No se encontró una API pública documentada para obtener
las fichas de inversión. No hay una integración autenticada implementada.

Se consulta el canal público `https://t.me/s/oportunidadesfactoringprestamype`,
que se presenta como oficial, aunque no se verificó su titularidad mediante un
enlace directo desde el sitio oficial. Solo sirve para medir actividad pública.
No sirve como prueba de disponibilidad, plazo, comisión o puntualidad.
Los avisos que muestran «operaciones pagadas» no prueban pago puntual.
Las imágenes sin texto interpretable, mensajes viejos y tasas imposibles se omiten.

La decisión del usuario es **no recibir preselecciones por verificar**. Sin
fichas completas el estado es «sin fichas completas: alertas bloqueadas».
Una ejecución exitosa en ese estado NO significa acceso a las fichas privadas.
No se envían mensajes de relleno. Los errores de lectura quedan visibles en
GitHub Actions, diferenciados de una ronda sana sin oportunidades.

## Selección

Todos los requisitos deben cumplirse; una tasa alta no compensa documentación
faltante. Las cifras de esta tabla son decisiones de filtro, no umbrales
extraídos de una tabla de morosidad de Prestamype.

| Comprobación | Regla inicial |
|---|---|
| Moneda y disponibilidad | Soles; ficha revisada hace como máximo 30 minutos |
| Riesgo publicado | A+, A o B, junto con revisión independiente del pagador |
| Factura | Conformidad, registro CAVALI y ausencia de disputa verificados |
| Pagador | Crédito vigente, finanzas y señales legales revisados; sin vinculación entre las partes |
| Historial | Cohorte completa de facturas vencidas: al menos 30, ventana mínima 180 días |
| Puntualidad | Al menos 95% pagadas a tiempo, sin impagas, castigadas ni mora actual; percentil 95 de atraso máximo 7 días |
| Plazo | Vencimiento más 30 días de margen dentro del horizonte personal |
| Diversificación | Hasta 5% del presupuesto por factura, 10% por pagador/grupo y 25% por sector |
| Saldo | Cartera completa y efectivo actualizados en las últimas 24 horas |
| Rentabilidad | Neta anualizada al menos 3 puntos sobre una referencia en soles vigente y comparable |
| Atraso | Con 30 días de atraso sin interés adicional, rentabilidad anualizada no inferior a esa referencia |
| Protección | Revisar garante, alcance, exclusiones, plazo de pago y solvencia; no reemplaza los otros requisitos |

Con horizonte de 90 días, el vencimiento contractual máximo inicial es 60 días
desde la evaluación. Los 30 días adicionales son un escenario prudente, **no
un límite real a una cobranza**. Si la protección tiene mayor plazo de pago,
se utiliza ese plazo en vez de 30. Ninguna alerta asegura liquidez a los 90 días.

Orden: categoría de riesgo, rentabilidad neta bajo atraso, puntualidad y menor
plazo. Máximo dos avisos diarios, una candidata por grupo económico en cada
lote. Los avisos respetan efectivo y concentración conjunta del lote. No
reservan capital; se debe actualizar la cartera tras cada inversión. La misma
factura no vuelve a notificarse durante 180 días. Solo se marca tras un envío
exitoso. Una alerta perdida se reintenta únicamente con datos todavía vigentes.

## Cálculo transparente

Se exige confirmar que la tasa de entrada sea efectiva anual y su base de
360 o 365 días. Interés bruto = capital × ((1 + tasa)^(días/base) − 1).
Se restan comisión sobre interés, IGV de esa comisión, retención sobre interés
bruto y otros cargos fijos. Las tasas/cargos no tienen valores predeterminados.
Las reglas tributarias y del contrato deben confirmarse para cada persona.

La anualización neta usa 365 días y el período desde hoy hasta vencimiento,
incluyendo la espera previa al financiamiento. El escenario de atraso mantiene
el mismo cobro neto y añade días. No promete reinversión ni intereses moratorios.
El umbral de pérdida con recuperación cero es solo sensibilidad matemática,
no una probabilidad estimada ni una razón suficiente para invertir.

## Evidencia y límites

- [Banco Mundial, Klapper, WPS3593](https://documents1.worldbank.org/curated/en/844291468321884034/pdf/wps3593.pdf): estudio histórico entre países que respalda la importancia de la información crediticia y del comprador. No estima riesgo de facturas de esta plataforma.
- [OCC, cuentas por cobrar](https://occ.treas.gov/publications-and-resources/publications/comptrollers-handbook/files/accts-rec-inventory-financing/pub-ch-accts-rec-inventory-financing.pdf): guía bancaria útil para revisar concentración, antigüedad, disputas y ajustes de facturas. No es regulación peruana ni valida nuestros cortes numéricos.
- [CAVALI, compradores](https://cavali.com.pe/solucion/facturas-negociables/compradores): conformidad y proceso de factura negociable; su registro no garantiza que el comprador pague.
- [SBS, registro de factoring](https://www.sbs.gob.pe/supervisados-y-registros/registros/empresas-de-factoring-no-comprendidas-en-el-ambito-de-la-ley-general): la inscripción no debe confundirse con protección de depósitos bancarios.
- [Prestamype, inversión](https://www.prestamype.com/invertir-factoring): acceso, advertencias y condiciones generales de la plataforma.
- [Prestamype, riesgos](https://www.prestamype.com/articulos/riesgos-inversion-factoring) y [oportunidades protegidas](https://www.prestamype.com/articulos/oportunidades-protegidas-inversion-segura-factoring): declaraciones comerciales; la protección añade exposición al garante y requiere contrato.
- [Simulador de Prestamype](https://sites.google.com/prestamype.com/simulador-factoring/inicio): referencia ilustrativa de cargos, que se deben reconfirmar antes de evaluar una ficha.

No se encontró información pública auditada suficiente por categoría, cohortes
y atrasos para determinar la tasa óptima o recomendar un pagador concreto.
No usar reseñas anecdóticas como frecuencia de impago. No confundir calificación
interna, respaldo contractual, conformidad y pago efectivo.

## Operación y datos privados

Workflow `factoring.yml`, cada 30 minutos (GitHub puede demorar la ejecución).
Como máximo tres solicitudes públicas por ronda, pausas de 1,5 segundos y
respeto de robots.txt y bloqueos. El lector público y las fichas revisadas son
entradas independientes: los anuncios públicos nunca completan datos privados.

Secretos de GitHub:

- `NTFY_TOPIC_FACTORING`: canal separado; opcionalmente `NTFY_TOKEN` para un servidor que lo requiera.
- `FACTORING_PROFILE_JSON`: objeto con `capital_pen` numérico, `currency: "PEN"`, `max_days` entero entre 1 y 90.
- `FACTORING_REVIEWS_JSON`: paquete privado descrito abajo. Ausente hasta tener evidencia completa.

No subir fichas, saldos o contratos al repositorio. `.private/` está ignorado.
Los nombres aleatorios de canales ntfy son enlaces de acceso, no cifrado de
extremo a extremo: compartirlos permite leer sus avisos. Enviar solo el resumen
de la candidata, sin documentos, números de cuenta ni cartera.
El estado versionado `state/factoring.json` contiene métricas agregadas, errores
genéricos y hashes de facturas ya notificadas; no contiene nombres ni posiciones.

Evaluación local sin enviar ni modificar estado:

```powershell
$env:FACTORING_PROFILE_JSON = Get-Content .private/factoring-profile.json -Raw
python -m monitor.factoring --sin-enviar --fichas .private/factoring-reviews.json
```

`--sin-enviar` puede mostrar el aviso privado en la consola local. No ejecutarlo
con fichas reales en registros públicos. La ejecución programada normal solo
imprime métricas agregadas. No hay mecanismo de actualización automática de
fichas: el paquete es una **normalización manual de evidencia**, no un formato
de exportación oficial. No renovar fechas sin volver a verificar las fuentes.

## Contrato del paquete revisado

Objeto con `reviews` (lista de hasta 100 fichas), `portfolio` y `benchmark`.
Todas las fechas/hora llevan zona horaria ISO 8601; las fechas simples son
`YYYY-MM-DD`. Montos y porcentajes son números JSON finitos, no textos. Los
campos booleanos exigen `true` o `false`; la ausencia no significa `false`.
Los porcentajes se expresan como 15 para 15%, no 0,15. Los identificadores de
pagador, factura, grupo y sector deben ser estables y normalizados.

Cada ficha debe contener:

- `reviewed: true`, `observed_at`, `available: true`, `currency: "PEN"`, `url` HTTPS de la ficha dentro de `www.prestamype.com/app/inversionista/`.
- `opportunity_id`, `invoice_id`, `payer_id`, `payer`, `group_id`, `sector`, `evidence_ref`: textos no vacíos. La evidencia privada debe permitir comprobar cada dato y la fuente de la revisión crediticia, financiera e histórica.
- `rate_type: "effective_annual"`, `day_basis` (360 o 365), `annual_pct`, `grade` (A+, A o B).
- `available_pen`, `minimum_pen`, `funding_date`, `due_date`. No confundir vencimiento con fecha garantizada de cobro.
- `fee_pct`, `fee_vat_pct`, `withholding_pct`, `withholding_base: "gross_interest"`, `fixed_cost_pen`. Los cargos fijos deben cubrir todos los costos incrementales del importe evaluado; si el contrato tiene otra base, no convertir por suposición: ampliar el adaptador antes de usarlo.
- `checks`: `checked_at` (máximo 7 días) y todos estos valores `true`: `invoice_accepted`, `cavali_registered`, `no_dispute`, `no_related_parties`, `credit_current`, `financials_reviewed`, `no_legal_red_flags`, `costs_confirmed`.
- `history`: `complete_matured_cohort: true`, `as_of` (máximo 24 horas), `window_days`, `matured`, `paid_on_time`, `paid_late`, `unpaid`, `written_off`, `currently_overdue`, `p95_delay_days`. Los cuatro estados deben ser mutuamente excluyentes y sumar `matured`; incluir también las facturas malas y los pagos tardíos. No usar solo los casos cobrados. Documentar el cálculo de atraso y ventana en la evidencia.
- `protected: false` o `true`. Si es `true`, `protection` exige `guarantor`, `conditions_ref` (alcance y exclusiones), `solvency_reviewed: true`, `reviewed_at` (máximo 7 días), `coverage_pct`, `payout_delay_days`. La protección nunca mejora artificialmente el historial observado.

`portfolio`: `complete: true`, `observed_at` (máximo 24 horas), `cash_pen` y
`positions` con todas las exposiciones vivas, incluso vencidas. Cada posición:
`invoice_id`, `payer_id`, `group_id`, `sector`, `principal_pen`. Una lista vacía
solo es válida si realmente no hay inversiones vigentes. No duplicar una
posición al sumar pagador y grupo.

`benchmark`: `currency: "PEN"`, `net_effective_annual: true`, `checked_at`
(máximo 7 días), `source_ref`, `max_lock_days`, `annual_pct`. Debe corresponder
a una alternativa accesible al usuario, después de costos y con liquidez
compatible; no usar tasas promocionales incumplibles ni comparar riesgo como
si fuera equivalente. El sistema valida campos y umbrales, no autentica la
veracidad de afirmaciones introducidas por el revisor.

Los casos sintéticos de `tests/test_factoring.py` son exclusivamente pruebas.
Nunca cargarlos como oportunidades reales.
