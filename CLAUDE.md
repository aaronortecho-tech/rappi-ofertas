# Monitor de ofertas de Rappi: guía para Claude Code

Este proyecto es un script de Python que corre en GitHub Actions cada 30 minutos. Busca descuentos altos en Perú y avisa al celular del usuario por ntfy, en cinco grupos con temas separados: `comida` (Rappi, Turbo, Tambo, Makro), `hogar`, `viajes`, `autos` e `inmuebles`. En ejecución no usa Claude. Claude Code solo interviene para instalarlo y para arreglarlo cuando Rappi cambie su web. El usuario habla español y no es programador, así que explícale cada paso en palabras simples.

## Estructura

- `monitor/catalogs.py`: grupos independientes hogar/viajes. Falabella/Sodimac usan `__NEXT_DATA__.props.pageProps.results`; se separan precios web de CMR y se calcula el porcentaje real sin redondear al alza. Diners usa tarjetas HTML `all__item` y condiciones con vigencias explícitas. Umbrales fijos: hogar 60 %, viajes 50 %. No tratar «hasta», cuotas o regalos como descuentos garantizados.
- `monitor/autos.py`: Neoauto por mapas del sitio y páginas de aviso (sin `?`). Memoria de precios por aviso en `state/autos.json`; año gratis, bajadas de precio y filtros de FUENTES.md.
- `monitor/inmuebles.py`: Nexo Inmobiliario (micro-zona de 1,5 km) y el PDF de adjudicados de Scotiabank (`pypdf`). `monitor/infocasas.py`: ventas y alquileres de los últimos 30 días para la rentabilidad por micro-zona. Memoria en `state/inmuebles.json`.
- `monitor/datos/aeropuertos.csv`: coordenadas públicas para medir vuelos en centavos por km.
- `.github/workflows/autos-inmuebles.yml`: cada 6 horas, grupo de `concurrency` propio. Secretos `NTFY_TOPIC_AUTOS` y `NTFY_TOPIC_INMUEBLES`; sin ellos solo junta datos.
- `FUENTES.md`: sitios por grupo, permisos, endpoints y trampas. Su sección "Estado real" manda sobre las tablas de investigación.
- `.github/workflows/catalogos.yml`: cada 30 minutos, dos temas y memorias separados. Secretos `NTFY_TOPIC_HOGAR`, `NTFY_TOPIC_VIAJES`. Comparte `concurrency` con Rappi. Ripley, LATAM y Despegar están excluidos por bloqueo; no simular su cobertura ni evadir controles. El grupo viajes sigue beneficios Diners y precios publicados JetSMART/SKY; no tarifas garantizadas en vivo.

- `monitor/main.py`: punto de entrada (`python -m monitor`). Coordina las secciones, filtra avisos repetidos y envía los mensajes.
- `monitor/scan.py`: revisa restaurantes (navegador), tiendas (HTTP, por turnos) y cadenas (respaldo).
  - Rappi Market/Turbo: añade `/lima/tiendas/marca-turbo` (usa `CIUDAD`) y lee los pasillos de hogar/bazar enlazados en cada local. `REVISAR_RAPPI_MARKET=si` por defecto. La caché de tiendas se renueva si cambian las fuentes. No amplía el límite de 40 tiendas por ronda.
- `monitor/browser.py`: Playwright. Abre `/restaurantes` con la cookie `currentLocation`, activa `#popular_filters-Promos`, captura la consulta `restaurants-bus/stores/filters` y la repite con `filters.discounts.types = ["offer_by_product"]` y `["percentage"]`. También pide `restaurants-bus/store/id/<id>/` para cada candidato. La ubicación se fuerza en todas las consultas con `page.route`.
- `monitor/parsers.py`: funciones puras que leen `__NEXT_DATA__` y el JSON de Rappi.
  - Tiendas: `price` y `real_price`.
  - Restaurantes (página pública): `price`, `realPrice` y `discountInPercent`.
  - Restaurantes (en vivo): `discounts[].price` y `discounts[].value`.
  - Lista de promos: `discount_tags[].tag` (el porcentaje está en el texto), `type` e `is_prime_exclusive`.
- `monitor/notify.py`: formato y envío a ntfy (POST JSON a `https://ntfy.sh/`).
- `monitor/state.py`: memoria en `state/state.json`, que el workflow guarda con un commit. Las claves se guardan como hashes SHA-256; no es cifrado.
- `monitor/config.py`: variables de entorno. Hay una tabla en README.md.
- `tests/`: pytest con copias reales recortadas de Rappi (`tests/fixtures`). `tests/test_browser.py` levanta un servidor local que imita a Rappi y ejecuta el monitor completo.

## Comandos

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q                                 # todas las pruebas deben pasar
python -m monitor --sin-enviar --prueba             # ronda real sin enviar avisos
DETALLE_EN_LOGS=si python -m monitor --sin-enviar   # con más detalle
```

En Windows PowerShell las variables se definen así: `$env:DETALLE_EN_LOGS = "si"`.

## Instalación (cuando el usuario lo pida)

1. Comprueba que existan `git` y `gh`. Si faltan, pide permiso antes de instalarlos (`winget install --id Git.Git` y `winget install --id GitHub.cli`).
2. Comprueba `gh auth status`. Si no hay sesión, pide al usuario que ejecute `gh auth login` en una terminal y elija el inicio de sesión por navegador. Tú no puedes completarlo.
3. Dentro de esta carpeta ejecuta:
   ```bash
   git init -b main && git add . && git commit -m "Monitor de ofertas Rappi"
   gh repo create rappi-ofertas --public --source . --remote origin --push
   ```
   El repositorio va público porque así GitHub Actions no tiene límite de minutos. Si el usuario lo quiere privado, cambia el cron a cada 2 horas y `MINUTOS_ENTRE_RONDAS` a `"120"`, y explícale el motivo.
4. Pide al usuario el nombre de su tema de ntfy y su ubicación (`latitud, longitud`, copiada de Google Maps). Guárdalos solo como secretos, nunca en archivos ni en commits:
   ```bash
   gh secret set NTFY_TOPIC --body "<tema>"
   gh secret set RAPPI_UBICACION --body "<lat>, <lng>"
   ```
5. Lanza la prueba y síguela:
   ```bash
   gh workflow run monitor.yml -f prueba=true
   gh run watch
   ```
   Confirma con el usuario que le llegó **🧪 Prueba del monitor de Rappi**. Si alguna sección falló, revisa `gh run view --log` y sigue la sección de mantenimiento.
6. Los ajustes opcionales van como variables: `gh variable set DESCUENTO_MINIMO --body "60"`.

## Grupos y fuentes nuevas

El estado real de cada grupo está en FUENTES.md, sección "Estado real". Las indicaciones de Cowork del 18 de septiembre se aplicaron con estos ajustes, que siguen vigentes:

- **Temas separados.** Cada grupo tiene su tema de ntfy y su memoria (`state/<grupo>.json`). El usuario lo eligió así; no volver a un tema único ni a una memoria compartida.
- **Sin reorganizar en `monitor/fuentes/`.** Rappi sigue en `main.py`/`scan.py`; los demás grupos pasan por `catalogs.run_group`, que recibe `(deals, reports)` de cada lector. Una fuente nueva es un lector que devuelve `Deal` y reportes.
- **`CatalogState.datos`** guarda la memoria propia de cada grupo (bandas de vuelos, avisos de autos, proyectos de Nexo). `Deal.reference_kind` en `flight_distance`, `autos` o `inmuebles` usa una clave estable: no se repite un aviso solo porque la mediana cambió.
- Autos e inmuebles: máximo 3 avisos por ronda, sin repetir en 60 días. Los nombres del report (`Neoauto/avisos`, etc.) deben ser fijos porque cuentan las fallas seguidas.

### Fuentes tipo VTEX (el camino más barato)

Una sola consulta por tienda trae lo más rebajado:

```
https://<tienda>/api/catalog_system/pub/products/search?O=OrderByBestDiscountDESC&_from=0&_to=49
```

Filtros de cordura obligatorios, porque el catálogo trae descuentos falsos: descartar productos sin `ListPrice`, con precio menor a S/ 10 o sin stock (`AvailableQuantity`), y deduplicar entre tiendas que comparten marketplace (Promart, Oechsle y Plaza Vea).

### Fuentes de viajes

El token de Travelpayouts va como secreto `TRAVELPAYOUTS_TOKEN`, nunca en el código. Lee la sección "El método que sí conviene para vuelos" de FUENTES.md antes de programar: el diseño cambió y el anterior no era viable.

- **Vuelos: invierte la consulta.** Usa `v1/city-directions?origin=LIM` (muchos destinos en una consulta) y `v2/prices/month-matrix` (un mes entero de una ruta en una consulta). **No** armes el monitor sobre `v1/prices/cheap` ruta por ruta y fecha por fecha: la combinatoria de origen, destino, ida y vuelta es de decenas de miles por ruta y revienta el presupuesto.
- **Vuelos: la medida es centavos por kilómetro**, además del mínimo histórico que ya existía (el usuario autorizó las caídas de 50 %; no se quitó). Distancia por fórmula desde un archivo público de coordenadas de aeropuertos (OurAirports u OpenFlights), sin consultas. Funciona desde la primera ronda, sin historia acumulada, y compara todos los destinos en una sola escala. Las bandas de referencia por tramo de distancia las calcula el propio monitor con lo que va juntando; no las inventes.
- **Nada de navegador para precios de vuelos.** Una sesión completa para obtener un número es el peor cambio posible. LATAM, SKY y JetSmart se leen solo como páginas de promociones en HTML, y sirven de vigía: cuando anuncian campaña, ahí sí vale gastar consultas de precio.
- **Todo aviso de vuelo es referencial.** Los datos de la API son búsquedas de otros usuarios guardadas 7 días: el aviso debe decirlo y llevar el enlace a la búsqueda en vivo.
- **Tours**: ahí sí funciona el mínimo histórico, porque un tour es un producto único sin combinatoria de fechas. **Hoteles**: compáralos contra su propia banda por mes, nunca contra un mínimo global.

### Grupo `autos`: el porcentaje se calcula, no se lee

Es el grupo más distinto de todos: nadie publica un precio de lista de un auto usado, así que el descuento hay que **calcularlo** contra los propios anuncios. El detalle verificado (mapas del sitio, forma de las direcciones, campos disponibles, umbrales y trampas) está en FUENTES.md; aquí va solo lo que cambia en el código.

- **Lectura barata**: `monitor/autos.py` lee `sitemap-avisos-autos-*.xml` y saca el id y el año de la dirección. **`<lastmod>` no sirve** (todas las entradas traen la hora de generación del archivo): se abren primero los avisos nuevos y después, por turnos, los leídos hace más tiempo (`LECTURAS_AUTOS`, 150 por ronda). Marca, modelo, precio, moneda y kilometraje salen de los datos schema.org de cada aviso. En Neoauto **nunca** uses direcciones con `?`: su robots.txt las prohíbe para todos.
- **Memoria de precios**: el `State` actual solo recuerda avisos ya enviados; autos necesita además un histórico por aviso (precio, fecha, kilometraje). Ponlo en `state/autos.json`, guardado por el workflow igual que el resto. Un aviso que desaparece del mapa del sitio se marca como vendido o retirado, no se borra: la historia es justamente lo que da valor.
- **El criterio de "súper oferta" está definido en FUENTES.md, sección "Qué cuenta como súper oferta". Léela antes de escribir un solo umbral.** Lo esencial: el porcentaje bajo la mediana **no** es el criterio principal, porque mientras más grande la rebaja, más probable es que la causa sea un defecto. El criterio principal es el **año gratis**: `precio ≤ mediana del mismo modelo del año anterior`. Se calcula con medianas por (modelo, versión, año), mínimo 8 comparables en el año del aviso y 8 en el año anterior.
- **Exige una sola anomalía.** Una ganga real es normal en todo menos en el precio. Si además el kilometraje no cuadra, o la versión no calza con el precio, o faltan datos, no se avisa. Cuenta las anomalías y descarta desde la segunda.
- **Páginas de anunciante** (`sitemap-anunciantes-revendedores.xml`, 58 concesionarios en `neoauto.com/<slug>`): cada una lista su inventario con precios. Úsalas para responder si el resto de los autos de ese vendedor está a precio de mercado; si todos están "baratos", no es descuento. Vale leer directo los canales de liquidación, por ejemplo `neoauto.com/dercocenter-liquidacion`.
- **El puntaje va antes del umbral**: junta año gratis, rebaja (saturada en 30 % y restando pasado el 35 %), retención relativa, historial del anunciante y bajadas de precio en un puntaje de 0 a 100, y avisa desde 70. Los pesos sugeridos están en FUENTES.md.
- **Normaliza la moneda antes de comparar** (`TIPO_CAMBIO`, configurable). Mezclar soles con dólares es lo que genera más falsas gangas.
- **Arranque en frío**: mientras un grupo no llegue a 8 comparables no se avisa nada. Que el registro lo diga ("juntando datos: N modelos con comparables suficientes") para que el usuario no crea que está roto.
- **Orden de trabajo**: primero el aviso por bajada de precio ("bajó 12 % y lleva 7 semanas publicado"): no necesita comparables, funciona desde la segunda ronda y es la señal más útil para este usuario. El año gratis y el puntaje vienen después, cuando haya comparables suficientes.
- **Sospechosos aparte**: por debajo del 55 % de la mediana, o con palabras como siniestrado, chocado o para reparar, no salen como oferta. Si salen, van marcados como sospechosos y explicando por qué.
- **Volumen**: ronda cada 6 horas, máximo 3 avisos por ronda, y un resumen semanal con las mejores oportunidades. El usuario no está comprando ahora: quiere pocas y buenas, no todas.
- **No automatices** la consulta de placa de SUNARP ni las de papeletas: son formularios del Estado con validación contra robots. El aviso lleva el enlace y nada más.

### Grupo `inmuebles`: la rentabilidad manda, no el precio por m²

El detalle verificado está en FUENTES.md, sección "Grupo 5 · Inmuebles". **Ojo:** Urbania, Adondevivir y RE/MAX quedaron fuera por el bloqueo de Cloudflare. Ventas y alquileres salen de Infocasas (`monitor/infocasas.py`, ruta `publicado-ultimos-30-dias`); además Nexo (preventa) y el PDF de Scotiabank. Donde abajo dice Urbania, léase Infocasas:

- **No uses las APIs internas.** Urbania y Adondevivir prohíben expresamente `/avisos-api/`, `/users-api/` y `/leads-api/` en su robots.txt. Devuelven JSON limpio y son la tentación obvia: no se tocan. Solo HTML y mapas del sitio.
- **Sí puedes pedir el orden por precio más bajo**, que ellos permiten a propósito: `?sort=low_price` en Urbania y `/*-ordenado-por-precio-ascendente*` en Adondevivir, hasta la página 5 (de la 6 en adelante está prohibido). Es el mismo truco del grupo `retail`: una consulta por distrito, tipo y operación trae primero lo más barato.
- **Hay que leer las dos operaciones.** El criterio principal es la rentabilidad implícita, así que cada micro-zona necesita sus ventas **y** sus alquileres: `rentabilidad = (alquiler mensual × 12) / precio de venta`, comparada contra la rentabilidad mediana de su propia micro-zona. Mínimo 8 comparables de cada lado.
- **Micro-zona, jamás distrito.** Los distritos de Lima mezclan realidades muy distintas y una mediana por distrito produce basura con cara de estadística. Usa la urbanización o el barrio del aviso, o una cuadrícula con sus coordenadas.
- **Nunca mezcles m² de terreno con m² construidos ni techados** en la misma mediana, y valida que el área sea verosímil.
- **Remates judiciales**: el descuento está en la ley, no en el aviso. Base = 2/3 de la tasación (art. 736) y −15 % por cada convocatoria sin postores (art. 742). Guarda el expediente y la convocatoria: el número de convocatoria da el descuento exacto. Ordena por convocatoria **baja**, no por descuento alto; los de cuarta o quinta casi siempre tienen un problema.
- **Adjudicados de bancos**: es un PDF mensual (~242 inmuebles en el de Scotiabank) con distrito, área, valor referencial y estado registral. Guarda el del mes anterior y compara: lo nuevo y lo que bajó es la señal. Los precios son referenciales, y el aviso debe decirlo.
- **La misma inversión que en autos**: más de dos veces la rentabilidad de la zona no es una ganga, es una advertencia. Satura la señal y hazla restar pasado ese punto.
- **Filtros obligatorios** antes de cualquier cálculo: descarta "derechos y acciones", aires, posesión sin título, sin saneamiento, en trámite de independización, anticresis, usufructo, bien futuro, y todo lo que diga ocupado o con posesionarios. Están enumerados en FUENTES.md.
- **No automatices SUNARP** ni las consultas de predial: el aviso lleva el enlace y el recordatorio de revisar la partida registral antes de cualquier decisión.

### Antes de dar por lista una fuente

1. Lee su `robots.txt` y respétalo; si el sitio responde 403 o 429, corta esa ronda.
2. Haz una consulta real y guarda una copia recortada en `tests/fixtures`, sin datos del usuario.
3. Escribe pruebas con esa copia y deja `python -m pytest -q` en verde.
4. Actualiza FUENTES.md con lo que aprendiste (campos, trampas, límites).

## Mantenimiento (cuando llegue "⚠️ El monitor de Rappi tiene problemas")

1. Revisa las últimas ejecuciones: `gh run list --workflow monitor.yml` y `gh run view <id> --log`.
2. Reproduce el problema localmente con `DETALLE_EN_LOGS=si python -m monitor --sin-enviar --prueba`.
3. Si Rappi cambió su web, abre la página en un navegador y compara con lo que esperan `browser.py` y `parsers.py`: el id del filtro, la ruta de la consulta, los nombres de los campos y la forma de `__NEXT_DATA__`.
4. Actualiza el código y, sobre todo, `tests/fixtures` con una copia recortada de la nueva respuesta. Nunca guardes coordenadas reales del usuario en esas copias. Luego ejecuta `python -m pytest -q`.
5. Haz commit y push. El workflow `Pruebas` corre solo; después lanza `gh workflow run monitor.yml -f prueba=true`.

## Reglas

- No evadas captchas ni bloqueos antibots. Si Rappi bloquea (403 o 429), el monitor debe parar esa ronda, no insistir.
- Mantén el ritmo: `PAUSA_ENTRE_CONSULTAS` de al menos 1 segundo. No subas `TIENDAS_POR_RONDA` (40) ni `MAX_RESTAURANTES_A_REVISAR` (30) sin necesidad, y no pongas rondas más seguidas que cada 30 minutos.
- No inicies sesión en Rappi, no uses la cuenta del usuario y no automatices compras.
- No agregues commits vacíos ni otros trucos para evitar que GitHub pause el workflow por inactividad.
- Privacidad: los registros de un repositorio público los puede ver cualquiera. No imprimas la ubicación, el tema de ntfy ni las distancias. Solo con `DETALLE_EN_LOGS=si` se muestran los nombres de los locales.
- Cada sitio tiene su límite y no se negocia: Neoauto prohíbe las direcciones con `?`, Autocosmos exige 20 segundos entre consultas y bloquea `/search`. Respétalos aunque el código funcione sin hacerlo.
- Urbania y Adondevivir muestran el desafío antibots de Cloudflare: no los agregues ni intentes evadirlo.
- PedidosYa bloquea el acceso automatizado con captcha: no lo agregues.

## Nuevas fuentes: estado y reglas vigentes

Lee FUENTES.md antes de ampliar. Su listado de candidatos no equivale a fuentes activas. La copia recibida se reconcilió con la versión desplegada, preservando Turbo, privacidad, errores visibles y pruebas.

- `monitor/vtex.py`: Promart, Oechsle, Estilos, Casaideas y Shopstar. 50 productos por tienda y ronda; verifica robots.txt antes del catálogo. Stock positivo, precio mínimo S/ 10, descuento calculado >=60 % y <95 %, categorías de hogar/tecnología. Copias recortadas reales en tests/fixtures/vtex_*.json.
- Se mantienen los tres temas ntfy y memorias separados existentes. No cambiar a un único tema, a una memoria compartida ni a frecuencias distintas por instrucciones de la propuesta original.
- Productos >=60 %; viajes >=50 %. No sustituir por alertas de 25 % de caída histórica. Travelpayouts no está habilitado y requiere acceso/token; las demás fuentes propuestas necesitan verificación.
- No publicar tópicos, ubicación, tokens ni respuestas VTEX completas (contienen campos de sesión innecesarios). Usar fixtures recortadas. Respetar bloqueos y robots.txt; no carrito, login ni compras.

- `monitor/flights.py`: JetSMART/SKY desde Lima, autorizados por el usuario. Comparar caída >=50 % con mínimo de 30 días y tres días previos de historial. Mantener moneda, tasas, fecha, aerolínea y condiciones en la identidad. Nunca convertir precios base SKY en totales ni tarifas publicadas en reservas confirmadas. `Deal.reference_kind=flight_history` tiene formato y moneda propios. Referencias pendientes de envío en `flight_alerts`, limitadas a siete días; solo reintentar si se vuelve a observar el mismo precio. Pruebas con fixtures públicas recortadas, sin motor de reservas.

- `monitor/convenience.py`: Tambo y Makro, grupo CLI `comida`, usa `NTFY_TOPIC` y state/comida.json. Respeta robots y bloqueo por dominio, umbral >=60 y <95 %, precio por presentación. No necesita secreto nuevo. Mass/Listo no activos.
- El usuario usa ntfy móvil y eligió claridad/separación: no insertar asteriscos Markdown ni caracteres de alfabetos alternativos para simular negrita. Mantener nombre, precio/descuento y referencia en renglones separados y condiciones visibles.
- `monitor/flights.py` (18 de septiembre): además de la caída histórica, mide centavos por km contra la banda de su tramo (mínimo 20 tarifas, aviso desde 50 % bajo la mediana, descarta bajo 20 %). Travelpayouts solo con el secreto `TRAVELPAYOUTS_TOKEN`, en cabecera, cada 6 horas.
- Hogar (18 de septiembre, pedido del usuario): se revisa cada 30 minutos y avisa en un resumen cada 3 horas (`hold_home` en `catalogs.py`, cola `datos.cola_hogar`, una entrada por `history_key` con el último precio; urgentes incluidas). 80 % o más sale en cada ronda con máximo 16 cupos si hay otras; el reloj `ultimo_resumen_hogar` solo avanza si el envío no falló. `Deal.note` se muestra pero no entra en la clave. No bajar la frecuencia de revisión para reducir avisos: el usuario pidió no perder ofertas.
- Un reporte cuyo error empieza con «revisión incompleta» cuenta para el aviso al celular tras 3 rondas, pero no pone el workflow en rojo (hoy: portada ligera de JetSMART).
- Calidad en hogar (`quality` en `catalogs.py`): puntaje = porcentaje + 12·log10(ahorro en S/) + 25 si es un nuevo mínimo frente al historial propio. Se descarta ahorro < `AHORRO_MINIMO_HOGAR` (20) y, con 7 días de historial al mismo precio (±2 %), el «descuento permanente». `Deal.rank` no entra en la clave.

- Deduplicación de hogar: `home_notice_key` se guarda en `State.seen` solo tras envío exitoso (7 días), además de las claves originales. `home_is_new` se usa en entrega y limpieza de cola. Un SKU compartido o un título completo con código de modelo permite unir vendedores; moneda, precio, categoría y condiciones deben coincidir. Nunca fusionar CMR con precio libre ni nombres genéricos con SKU distintos.

## Selección y vigencia de hogar (actualización vigente)

Esta sección reemplaza las reglas anteriores de urgencia por porcentaje y descarte automático por precio estable. Umbral publicado >=60%; >=80% solo es urgente con mínimo tres días previos comparables y caída >3% contra el mínimo de 30 días. `quality` etiqueta evidencia histórica, pesa más que la referencia tachada y baja prioridad de precios estables sin declararlos falsos. `balanced` reparte cupos por categoría antes de recortar 300 no urgentes.

`monitor/home_validation.py` recorre progresivamente las candidatas ordenadas hasta confirmar 24 ofertas: observación de la ronda o relectura del catálogo de `Deal.check_url` (campo fuera de claves). Máximo 8 páginas/16 solicitudes extra, incluidas robots/reintentos; ninguna consulta tras bloqueo de la fuente. Cambios de precio se guardan para reevaluar, ausencia/error conserva pendiente sin avisar. No introducir consultas a producto o APIs nuevas sin validar fuentes. Las entradas viejas sin check_url esperan ser observadas otra vez. Métricas por ronda y totales diarios 28 días, sin confundir observaciones con productos únicos diarios.

- Selección progresiva: `run_group` no recorta 24 candidatas antes de `validate`. `MAX_CONFIRMED=24` cuenta confirmadas únicas; `MAX_PAGES=8` y `MAX_REQUESTS=16` siguen acotando la red. Sin cupo de red se admiten solo observaciones de la ronda o páginas ya leídas. Métricas separan `candidatas_disponibles`, `consideradas`, `listas_para_enviar` y `enviadas`; `seleccionadas` conserva el significado histórico de intentos considerados.

- Alternativas equivalentes: antes de validar, `home_order(..., keep_alternatives=True)` conserva vendedores equivalentes y prefiere los observados en la ronda. Solo al confirmar uno se omiten los demás, sin nuevas consultas. En entrega se mantiene la deduplicación persistente. Los lotes avanzan por los productos efectivamente incluidos tras ajustar longitud; máximo ocho mensajes (tres en autos/inmuebles), sin marcar ofertas omitidas ni envíos fallidos.
