# Segunda evaluación — 18/09/2026

Revisión de e9755b8 y 4d5a451 frente a 3e50f2c. Copia local limpia en 3c9312f. Los commits remotos posteriores comprobados (666f800, 681dccc) solo actualizan memoria. No se modificó el código ni se enviaron notificaciones durante esta evaluación.

## Resultado
Mejora real, pero corrección parcial. 208 pruebas locales pasan. Las ejecuciones posteriores revisadas de Rappi y catálogos son exitosas. Eso no demuestra aún mejor selección de oportunidades en viajes/autos/inmuebles.

## Hallazgos reproducidos

1. Prioridad alta — Autos sigue aceptando comparables de versiones diferentes (monitor/autos.py:210–224). Se mantiene expresamente el respaldo al modelo completo. Usando los datos sintéticos de sus propias pruebas, un Sorento de versión «raro» sin comparables de esa versión obtiene 72/100 y alerta de «año gratis» a US$14.800. La salida no aclara que mezcla versiones. Mantener la misma granularidad entre años es mejor, pero no resuelve la comparabilidad. Separar esa señal como exploratoria o exigir versión suficiente; la bajada histórica del propio anuncio puede continuar sin comparables.

2. Prioridad media — El cursor de Rappi no cumple la continuidad prometida en todos los casos. Si la segunda petición recibe 403, la primera ya se procesó, pero next_start queda en cero: la excepción salta la actualización en scan.py:265. Además, State.set_stores (state.py:147) elimina next_start al renovar la lista cada 24 horas. Se reprodujeron ambos casos sin red. Preservar el avance confirmado al abortar y trasladar el cursor por identificador al renovar el catálogo. No reintentar el sitio bloqueado en esa ronda.

3. Prioridad media — JetSMART convierte dos lecturas sin catálogo en «0 revisados · OK» las primeras dos rondas (flights.py:229–261). Reduce estados rojos, pero no aumenta cobertura y oculta revisión incompleta. Si persiste, el lector empieza a fallar en la tercera ronda; el contador adicional de catalogs.py:429 llega a tres fallas en la quinta ronda. Diferenciar revisión incompleta de lectura exitosa, manteniendo por separado la política de avisos al celular.

## Cambios bien encaminados
- Rappi solo marca los 15 locales mostrados en el resumen, conservando los demás como no notificados.
- Cursor persistente y copia independiente de store_list al serializar: funcionan entre rondas normales, con regresiones automatizadas.
- Autos excluye comparables con daños y kilometraje anómalo.
- Infocasas deduplica comparables por ubicación y área; reduce republicaciones, aunque una cuadrícula redondeada no garantiza identidad del inmueble y puede fusionar unidades de un edificio.
- Travelpayouts advierte diferencias de duración y condiciones. Esto mejora el texto; no valida todavía la equivalencia entre fechas.
- Se conservan las tres correcciones de la primera evaluación.

## Evidencia real posterior
- Rappi, ejecución 35390891407: 172 restaurantes, 40 tiendas desde posición 161, siete anuncios >=60%, cero avisos nuevos. Éxito. https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35390891407
- Catálogos, ejecución 35387935694: hogar 717 candidatos, 24 productos enviados; JetSMART y SKY 12 tarifas cada uno, Diners 12 promociones, viajes cero avisos; Tambo 79 y Makro 10 revisados, cero candidatos. Éxito. https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35387935694
- La ejecución de autos/inmuebles más reciente en el listado examinado precede los cambios externos: su efecto productivo todavía no está probado.

## Pendientes de eficacia
No cambiaron selección de hogar, cola persistente ni métricas de cobertura. Esperar historial para valorar ahorro real es razonable; contar únicos, aplazados y antigüedad no requiere esperar semanas. La afirmación de que los excedentes «llegarán en las próximas rondas» sigue siendo condicional: deben volver a aparecer y continuar vigentes. Sin cola persistida no existe garantía.

Validación: 208 pruebas en 28,86 s; reproducciones aisladas en reevaluacion_repros.py. Los problemas anteriores no son fallos de estas pruebas: son escenarios adicionales o comportamientos aceptados explícitamente por ellas.

## Respuesta y cambios aplicados (Claude Code, 18 de septiembre de 2026)

Los tres hallazgos se reprodujeron con `reevaluacion_repros.py` y quedaron corregidos; el mismo guion ahora da cursor 1 tras el bloqueo, cursor conservado al renovar la lista y ningún aviso para la versión sin comparables.

1. **Autos.** Un aviso con versión declarada solo se compara con esa versión, en su año y en los anteriores; sin comparables de su versión no hay «año gratis» (la bajada de precio del propio aviso sigue). Los avisos sin versión declarada se comparan con el modelo completo y el mensaje lo dice: «comparado con todas las versiones del modelo».
2. **Cursor de Rappi.** Avanza tienda por tienda, así que un 403 a mitad del grupo conserva lo ya revisado y deja la tienda bloqueada para la ronda siguiente (sin reintentarla en esa ronda). Al renovar la lista cada 24 h el cursor sigue a la misma tienda por su id (o a la siguiente si desapareció).
3. **JetSMART.** La portada ligera dos veces seguidas ya no es «0 revisados · OK»: se informa como «revisión incompleta» en el registro, la prueba y el resumen de GitHub. Cuenta para el aviso al celular (tercera ronda seguida) pero no vuelve roja la ejecución; en la tercera ronda seguida el lector sí falla (rojo).

Además, a pedido del usuario: **hogar avisa en un resumen cada 3 horas** sin bajar la frecuencia de revisión (sigue cada 30 minutos). Las candidatas esperan en una cola persistente (`datos.cola_hogar`, una por producto, el último precio, 24 h sin volver a verse la retiran); 80 % o más se envía en la misma ronda. Esto cubre para hogar la «cola persistente» pedida en ambas evaluaciones. El texto de los excedentes de Rappi ahora dice «si siguen vigentes, salen en la próxima ronda».

Sobre la cuadrícula de Infocasas: sí puede fusionar dos unidades del mismo edificio con igual área; el error va en la dirección conservadora (menos comparables, menos avisos), por eso se mantiene.

Siguen pendientes: métricas de cobertura por ronda (únicos, aplazados, antigüedad) y cola persistente para Rappi.

