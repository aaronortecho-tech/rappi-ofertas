# Evaluación del monitor — 18 de septiembre de 2026

## Conclusión
El sistema es coherente como detector de candidatos y ya entrega alertas reales en Rappi y hogar. Todavía no está demostrado que seleccione las mejores oportunidades ni que cubra todo el catálogo. Viajes, autos e inmuebles siguen acumulando referencias; su funcionamiento técnico no equivale a eficacia demostrada en ofertas.

## Evidencia revisada
Código local basado en 8456b3b; 100 ejecuciones entre 17/09 21:47 UTC y 18/09 18:25 UTC; cuatro registros completos seleccionados, memoria persistida y suite automatizada. La muestra incluye cambios de versión y ejecuciones manuales: no es una tasa estable de disponibilidad.

- Rappi: 41 ejecuciones, todas verdes. La última examinada revisó 175 restaurantes y 40 de 537 tiendas, encontró 7 restaurantes con anuncios >=60% y envió 2 avisos. La rotación comprende 14 grupos; no se revisa cada tienda cada 30 minutos. Intervalos reales del programador: 22,8–43 minutos. Turbo tuvo cero locales en ese grupo, lo que no implica que esté desactivado.
- Hogar/viajes: 47 ejecuciones, 39 exitosas y 8 fallidas. En el fallo examinado 35373797316, JetSMART no entregó catálogo; hogar y comida sí se ejecutaron. La última ronda 35380090805 revisó 1.056 entradas de retail (pueden incluir duplicados), encontró 710 candidatos y envió 24 productos. La memoria registra 1.224 claves notificadas de hogar; no son necesariamente 1.224 productos únicos.
- Tambo/Makro: 79 y 10 entradas, cero candidatos >=60%. Confirma lectura parcial, no ausencia de ofertas en todo el comercio.
- Viajes: última ronda examinada: Diners 12 promociones, JetSMART 12 tarifas, SKY 12 tarifas, cero avisos. Memoria con 84 historiales de un solo día: todavía no alcanza los tres días necesarios. Las bandas de distancia contienen entre 2 y 12 tarifas cada una, todas bajo el mínimo 20. Travelpayouts sí dejó bandas de 29 tarifas repartidas en cuatro grupos; su secreto está configurado. Las páginas pequeñas pueden tardar mucho en reunir suficientes observaciones comparables.
- Autos/inmuebles: una ejecución examinada, 35378171836, exitosa. Autos: 150 avisos, cero modelos-año con ocho comparables, cero avisos enviados. Inmuebles: 57 proyectos Nexo, 94 ventas y 35 alquileres Infocasas en memoria; 242 filas del PDF bancario revisadas; cero avisos enviados.
- Pruebas en la muestra: 9 ejecuciones exitosas y 2 fallidas durante desarrollo. No confundirlas con fallos del monitor productivo.

En Rappi, algunos errores de fuente no vuelven roja cada ejecución: el resultado depende también de cuándo se notifica el fallo. Por eso los 41 estados verdes no prueban cobertura completa. Los textos `echo ::error::` presentes en el script del workflow tampoco prueban que ese comando se haya ejecutado.

## Correcciones de esta revisión
1. Autos e inmuebles entregaban solo los tres primeros candidatos al filtro de repetidos. Si esos tres ya estaban notificados, otras oportunidades quedaban fuera. Ahora el límite de tres se aplica después de deduplicar.
2. Infocasas conservaba la búsqueda, pero no la página cuando agotaba el presupuesto. Una búsqueda larga podía reiniciarse indefinidamente. Ahora persiste y retoma la página siguiente, incluso tras interrumpirse.
3. Autos priorizaba todo el inventario desconocido antes de releer precios. Ahora reserva un tercio del presupuesto para los conocidos, ordenados por antigüedad de lectura. Mejora la detección de bajadas, a cambio de una primera exploración algo más lenta.

Estas correcciones no cambian los descuentos mínimos ni los temas de ntfy. No resuelven todavía una cola persistente de todos los candidatos: una oportunidad no enviada debe volver a aparecer en una lectura posterior.

## Mejoras prioritarias pendientes

### Alta: calidad de las referencias
- Hogar: el descuento anunciado no prueba ahorro frente al mercado. Mantener >=60% como filtro de entrada y ordenar también por historial, ahorro absoluto y diversidad reduciría ruido. No convertir un precio tachado elevado en prueba de ganga. El historial actual solo tiene uno o dos días.
- Autos: el criterio año gratis permite referencias generales del modelo cuando faltan versiones; las escalas de años anteriores también mezclan versiones. Exigir versión comparable y depurar anuncios anómalos antes de construir medianas. Hoy no hay suficiente muestra para validar esos avisos.
- Inmuebles: los comparables no eliminan republicaciones del mismo inmueble con otro identificador y permanecen hasta 120 días. Ocho anuncios no garantizan ocho propiedades distintas ni vigencia. Incorporar deduplicación espacial y antigüedad de observación antes de confiar en rentabilidades.
- Vuelos: el coste/km es una comparación estadística por distancia, no un descuento sobre la misma ruta, fecha y equipaje. Separar su presentación del descuento histórico. La comprobación mensual de Travelpayouts requiere validar duración y condiciones antes de sugerir otras fechas como equivalentes.

### Alta: medir cobertura y entrega útil
- Registrar por ronda productos únicos, catálogo esperado, páginas pendientes, candidatos nuevos, descartes, entregados y aplazados. Mantener una cola de candidatos aún vigentes para no perderlos al rotar páginas.
- La rotación de Rappi depende del reloj: retrasos del programador pueden repetir/saltar grupos. Un cursor persistente debe avanzar solo después de completar el grupo.
- Los resúmenes de excedentes Rappi muestran hasta 15 locales, pero marcan el resto como notificado: algunas oportunidades pueden quedar ocultas. Solo marcar lo efectivamente mostrado o conservar una cola.
- Distinguir claramente fuente bloqueada, catálogo vacío, historial insuficiente y revisión exitosa. El estado verde del workflow debe representar salud técnica; la alerta al celular puede seguir limitada para evitar ruido.

### Media: frecuencia y experiencia
- Hogar y páginas públicas de vuelos se revisan cada 30 minutos, aunque FUENTES propone 3 y 6 horas respectivamente. Travelpayouts ya respeta seis horas. Evaluar reducir frecuencia de catálogos lentos tras medir cambios efectivos; preservar la frecuencia de comida.
- Mantener el formato móvil sencillo. Considerar resumen de hogar o menor volumen si 24 productos por ronda resulta excesivo. No se modificó esta preferencia automáticamente.
- Actualizar documentación: quedan párrafos que dicen Travelpayouts no probado e Infocasas pendiente, pese a datos reales persistidos.

## Qué falta para demostrar eficacia
Además de ejecutar sin errores, comprobar durante varias semanas: cobertura real de cada fuente, proporción de avisos con stock/precio vigente al abrirlos, duplicados percibidos, ofertas que se perdieron y utilidad de los avisos. ntfy confirma aceptación del envío; los registros no prueban lectura en el celular ni disponibilidad final al comprar. No se realizaron compras ni se validaron manualmente todas las ofertas.

## Registros
- Rappi: https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35379834446
- Hogar, viajes y comida: https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35380090805
- Fallo de JetSMART: https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35373797316
- Autos e inmuebles: https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35378171836

## Respuesta y cambios aplicados (Claude Code, 18 de septiembre de 2026)

Las tres correcciones de la revisión se verificaron y se conservan: el límite de tres avisos se aplica después de deduplicar, Infocasas retoma la página y autos reserva un tercio de lecturas para precios conocidos (la primera exploración completa pasa de ~7 a ~10 días).

Aplicado a partir de las mejoras pendientes:

- **Rappi, resumen de excedentes.** Confirmado: se marcaban como avisados todos los locales aunque el mensaje mostrara 15. Ahora solo se marcan los mostrados; el resto vuelve a salir en la ronda siguiente.
- **Rappi, rotación por reloj.** Confirmado: con intervalos reales de 22 a 43 minutos se repetían o saltaban grupos. Ahora hay un cursor en `state.json` (`store_list.next_start`) que avanza solo lo que se alcanzó a revisar; si se acaba el tiempo o hay bloqueo, la ronda siguiente continúa desde ahí.
- **JetSMART en rojo.** 3 de 29 rondas fallaron porque la portada ligera llegó dos veces seguidas. Ahora una ronda así queda sin tarifas pero verde; tres rondas seguidas sí es error (cambio de formato probable). Una página que no sea la portada de JetSMART sigue fallando de inmediato.
- **Autos, medianas.** Los avisos con palabras de alerta o kilometraje raro ya no entran en las medianas. La escalera del año gratis usa una sola granularidad: todo por versión si hay medianas de la versión para ese año y el anterior; si no, todo por modelo. Se mantiene el respaldo por modelo porque muchos avisos de Neoauto no traen versión: exigir versión dejaría el grupo casi sin señales.
- **Inmuebles, republicaciones.** Los comparables se deduplican por ubicación (~10 m), área y operación; un inmueble publicado a la vez en venta y en alquiler en el mismo punto no se usa como comparable de sí mismo. Se mantiene la ventana de 120 días para alquileres: la ruta de 30 días de Infocasas ya filtra lo viejo y sin esa ventana no se llega a 8 comparables.
- **Vuelos.** El coste por km ya tenía un formato propio ("medida en centavos por km, no descuento anunciado"). Las otras fechas de `month-matrix` ahora advierten que la duración y las condiciones pueden ser otras.
- Documentación: Travelpayouts figura como probado en vivo.

No aplicado, a propósito:

- **Frecuencia y volumen de hogar** (24 productos en una ronda). Es una preferencia del usuario; se le consulta antes de cambiarla.
- **Orden de hogar por historial y ahorro absoluto.** El historial tiene uno o dos días; conviene esperar unas semanas de datos antes de cambiar el orden.
- **Cola persistente de candidatos y métricas por ronda** (únicos, pendientes, aplazados). Útil pero es un cambio mayor; con los arreglos de arriba ya no se pierden candidatos por el resumen de Rappi ni por el límite de autos e inmuebles. Queda como siguiente paso si el usuario quiere medir cobertura.

