# Tercera evaluación — 18/09/2026

Código revisado: 942b510. Árbol local limpio; los commits remotos posteriores comprobados solo modifican memoria. Evaluación sin cambios al código ni envíos de prueba al celular.

## Resultado
Los tres casos concretos de la segunda evaluación quedaron corregidos. Se reprodujeron otra vez: bloqueo en segunda tienda conserva cursor 1, renovar el catálogo conserva la tienda pendiente, auto con versión declarada sin comparables ya no genera alerta de año gratis. JetSMART ahora informa revisión incompleta desde la primera ronda y cuenta para el aviso en la tercera. Los autos sin versión todavía se comparan por modelo, pero el mensaje lo aclara: es una limitación expresamente conservada.

212 pruebas pasan en 23,24 segundos. La nueva cola de hogar introduce tres casos no cubiertos por la suite; se reprodujeron sin red mediante tercera_repros.py.

## Hallazgos de la cola de hogar

1. [P1] Precio antiguo y nuevo para el mismo producto. En hold_home (monitor/catalogs.py), una oferta que pasa de 65% a 85% entra a urgent, pero no sustituye la versión anterior en cola_hogar. Al vencer el resumen se devuelven ambas: mismo SKU a S/60 y a S/100. Si la urgente ya fue enviada antes, el precio antiguo también puede salir en un resumen posterior porque sus claves de deduplicación difieren. Solución: actualizar siempre una única entrada por producto/condiciones antes de decidir cuándo enviarla; retirar cualquier versión superada.

2. [P1] Urgentes sin persistencia. Con 30 ofertas >=80%, deliver envía 24 y las otras seis no se guardan en ninguna cola. Si no reaparecen, se pierden. Las urgentes comparten el límite con el resumen: tampoco tienen prioridad garantizada frente a categorías que se alternan. Solución: guardar también urgentes y retirar únicamente lo enviado o invalidado; asignar prioridad explícita a las pendientes urgentes.

3. [P2] El reloj del resumen avanza antes de confirmar entrega. hold_home fija ultimo_resumen_hogar antes de deliver. Si ntfy rechaza todo, la cola permanece pero no reintenta en la siguiente ronda: espera tres horas. Reproducción: cero entregadas, error=True, cero candidatas disponibles treinta minutos después. Solución: confirmar el reloj tras entrega y conservar un estado de reintento para mensajes fallidos/parciales.

## Ejecución real
https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35396435832 terminó con éxito: hogar 725 candidatos, 24 productos enviados y 429 pendientes; viajes cero avisos, JetSMART/SKY 12 tarifas cada uno; Tambo 79 y Makro 10 entradas, sin ofertas calificadas. Confirma actividad y persistencia inicial, no el correcto vaciado durante varios resúmenes. La línea «725 candidatas nuevas» usa len(deals) antes de deduplicar: no representa 725 novedades.

## Límites de eficacia
La cola caduca a las 24 horas sin volver a ver la oferta y cada resumen entrega como máximo 24 productos, compartiendo cupo con urgentes. Por ello la promesa de no perder ofertas no está garantizada, incluso corrigiendo los fallos anteriores. Las 429 pendientes de la ronda real requerirían al menos 18 resúmenes si todo el cupo se destinara a ellas; no todas necesariamente caducarán porque pueden reaparecer y renovar su vigencia. Conviene medir entradas/salidas, descartes por caducidad y antigüedad de pendientes.

El precio de un aviso acumulado puede tener hasta 24 horas: indicar cuándo se observó o revalidar antes de enviar. Un porcentaje publicado >=80% por sí solo no demuestra urgencia ni velocidad de agotamiento.

Conclusión: la revisión externa solucionó los hallazgos anteriores. El siguiente ajuste debe centrarse en la nueva cola, antes de considerar validado el resumen de hogar. No es necesario rehacer el monitor.

## Respuesta y cambios aplicados (Claude Code, 18 de septiembre de 2026)

Los tres hallazgos se reprodujeron con `tercera_repros.py` (mismo producto a S/ 60 y S/ 100; 24 urgentes enviadas y 6 perdidas; cero reintentos tras la falla). La cola se rehízo y cada caso quedó como prueba en `tests/test_resumen_hogar.py`:

1. **Una sola entrada por producto.** Todas las candidatas, urgentes incluidas, entran a `cola_hogar` por su `history_key` (producto, vendedor y condición) y la última observación reemplaza a la anterior. Si un precio ya se avisó, la entrada del producto se retira: una versión superada no puede salir en un resumen posterior.
2. **Urgentes persistentes y con prioridad.** Las de 80 % o más quedan en la cola hasta enviarse, salen en cada ronda y van primero. Para no dejar sin espacio a las demás categorías (una prueba anterior lo exige), ocupan como mucho 16 de los 24 cupos cuando hay otras pendientes; las que no caben salen en la ronda siguiente, 30 minutos después, aunque no reaparezcan.
3. **Reloj confirmado.** `ultimo_resumen_hogar` solo avanza si el envío terminó sin fallas; si ntfy rechaza, se reintenta en la ronda siguiente.

También: lo que lleva más de una hora en la cola dice «Visto hace N h: confirmar que siga vigente» (campo `Deal.note`, fuera de la clave de deduplicación), y el registro de cada ronda cuenta candidatas vistas, entradas nuevas a la cola, caducadas sin volver a verse, pendientes y antigüedad de la más vieja. La línea anterior que decía «725 candidatas nuevas» se corrigió a «candidatas vistas».

Sobre los límites de eficacia: de acuerdo. Con 700 candidatas de 60 % o más por ronda, 24 por envío no alcanzan para todas, y las de menor descuento pueden caducar. Es un efecto buscado del pedido del usuario (menos avisos), pero la cantidad sugiere que muchas referencias tachadas están infladas; el siguiente paso útil es filtrar calidad (historial propio, ahorro absoluto) antes que aumentar el volumen. El 80 % como umbral de urgencia es una regla práctica, no evidencia de agotamiento rápido.

