# Cuarta evaluación — 18/09/2026

Versión: 6086972, árbol local limpio; comparación con GitHub sin commits posteriores al consultar. Evaluación sin cambios de código, despliegues ni notificaciones de prueba.

## Veredicto
Los tres fallos de la tercera revisión están corregidos. 219 pruebas pasan en 28,34 s. Hay dos hallazgos nuevos y acotados en las funciones añadidas; no justifican rehacer el sistema.

## Correcciones confirmadas
- Precio anterior superado al pasar a urgente: la cola devuelve únicamente el nuevo precio (S/60 en la reproducción; ya no S/100).
- Urgentes fuera del límite de envío: con 30 ofertas se envían 24 y seis quedan para la siguiente ronda, aunque no reaparezcan.
- Envío fallido: el reloj no avanza y la regresión automatizada confirma reintento en la siguiente ronda. Se indica antigüedad de observación.
- Mejora de selección: incorpora ahorro absoluto y bajadas frente al historial propio, conserva métricas de cola y limita su tamaño.

## Hallazgos pendientes

### P2 — La deduplicación entre vendedores no persiste entre rondas
monitor/catalogs.py:460–467 deduplica por nombre normalizado y precio solo en una lista temporal. Al enviar, la línea 500 marca únicamente la clave del vendedor elegido; la otra permanece pendiente y es enviada en el resumen siguiente. Reproducción sin red: dos entradas del mismo nombre/precio, vendedores diferentes; primera ronda una enviada, segunda ronda otra enviada. La promesa «sale una sola vez» no se cumple entre rondas.

Recomendación: persistir una identidad compartida de notificación para equivalencias verificadas o registrar las alternativas suprimidas tras confirmar el envío. No usar solo un nombre genérico para asumir que productos distintos son equivalentes; mantener vendedor/condiciones cuando cambien la oferta.

### P2 — El máximo de 300 también descarta urgentes
monitor/catalogs.py:437–442 ordena urgentes primero, pero elimina todo lo que queda después de la posición 300. Con 301 urgentes, conserva 300 y descarta una. Contradice comentario y README «las de 80% o más nunca se recortan». Caso límite reproducido, no pérdida comprobada en producción.

Recomendación: decidir y documentar una regla coherente: límite explícito también para urgentes, o reservarlas fuera del recorte. Si deben conservarse todas, probar específicamente un volumen urgente superior al máximo.

## Evidencia real y alcance
La última ejecución de catálogos examinada, 35407122285, fue exitosa, con 735 candidatos vistos, siete descartes por ahorro menor a S/20, un producto enviado y 1.444 pendientes. JetSMART informó correctamente revisión incompleta. Esta ejecución corresponde al código ANTERIOR al límite de 300: no demuestra que el nuevo límite haya sido ejecutado en producción.

https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35407122285

El commit 6086972 tiene CI exitoso:
https://github.com/aaronortecho-tech/rappi-ofertas/actions/runs/35407254988

## Límites de la selección
El filtro de siete observaciones diarias parecidas es una heurística de estabilidad, no prueba que el precio anterior sea ficticio. El ahorro absoluto todavía se calcula contra la referencia publicada por el vendedor; únicamente el componente histórico está basado en observaciones propias. Los nuevos filtros pueden reducir ruido, pero se necesita observar varios ciclos de resúmenes para medir cobertura y utilidad. No se verificó stock final ni se hicieron compras.

Reproducciones: cuarta_repros.py, sin red ni escritura al estado productivo. Los dos hallazgos nuevos no están cubiertos por la suite actual.

## Respuesta y cambios aplicados (Claude Code, 18 de septiembre de 2026)

Ambos hallazgos se reprodujeron con `cuarta_repros.py` y quedaron corregidos; el mismo guion ahora da cero envíos en la segunda ronda para la copia del otro vendedor y 301 urgentes conservadas.

1. **Copias entre vendedores.** Al enviar un producto se marcan como avisadas también sus copias de otros vendedores o tiendas, así que no salen en el resumen siguiente. Para no fundir productos distintos con nombre parecido, la equivalencia exige nombre normalizado, precio **y categoría** iguales; con otra categoría se tratan como productos distintos. Sigue siendo una heurística por nombre: si el vendedor cambia precio o condiciones, la oferta vuelve a ser distinta.
2. **Límite y urgentes.** Regla elegida: el máximo de 300 se aplica solo a las no urgentes (las mejores por puntaje); las de 80 % o más quedan fuera del recorte porque salen en cada ronda. Probado con más urgentes que el límite.

Sobre los límites de la selección: de acuerdo. Siete días al mismo precio es una heurística de estabilidad, no una prueba de que el «antes» sea ficticio, y el ahorro en soles todavía usa la referencia del vendedor. Se evaluará con varios ciclos de resúmenes antes de endurecer o relajar reglas.

