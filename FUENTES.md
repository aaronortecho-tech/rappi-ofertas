# Fuentes de ofertas en Perú

Guía de los sitios que se pueden vigilar, ordenados en cinco grupos. Todo lo marcado como **verificado** se probó el 17 de septiembre de 2026: se leyó el `robots.txt` del sitio y, cuando correspondía, se consultó su catálogo real.

Cómo leer la tabla:

- **Permiso**: lo que el sitio declara en su `robots.txt`. No reemplaza a sus términos de uso, que pueden decir otra cosa y cambian sin aviso.
- **Vía**: cómo se obtienen los datos, de más fácil a más difícil: API oficial → catálogo VTEX → HTML → navegador oculto (Playwright).

Reglas que valen para todas las fuentes: al menos 1 segundo entre consultas, sin iniciar sesión, sin comprar nada, cortar la ronda si el sitio responde 403 o 429, y nunca evadir captchas.

---

## Estado real · 18 de septiembre de 2026 (leer primero)

Las tablas de cada grupo, más abajo, son la investigación de Cowork del 17 y 18 de septiembre: explican el porqué del diseño. Donde chocan con lo que se comprobó al programar, manda esta sección.

| Grupo | Tema ntfy | Activo | Frecuencia real |
|---|---|---|---|
| `comida` | `NTFY_TOPIC` | Rappi y Rappi Market/Turbo, Tambo, Makro | 30 min |
| `hogar` (el `retail` de las tablas) | `NTFY_TOPIC_HOGAR` | Falabella, Sodimac, Promart, Oechsle, Estilos, Casaideas, Shopstar | 30 min |
| `viajes` | `NTFY_TOPIC_VIAJES` | Diners, JetSMART y SKY (caída histórica y centavos por km); Travelpayouts solo con `TRAVELPAYOUTS_TOKEN` | 30 min; Travelpayouts cada 6 h |
| `autos` | `NTFY_TOPIC_AUTOS` | Neoauto (nuevos, seminuevos y usados) | 6 h |
| `inmuebles` | `NTFY_TOPIC_INMUEBLES` | Infocasas (ventas y alquileres: rentabilidad), Nexo Inmobiliario (preventa) y adjudicados de Scotiabank | 6 h; Nexo cada 12 h, Scotiabank cada semana |

Correcciones a las tablas de abajo, comprobadas con lecturas reales:

- **Diners** sí responde y está activo desde el 17 de septiembre (la tabla dice error 405). **Falabella** entrega sus precios en el HTML con JSON integrado: no hace falta navegador. **Sodimac** está activo con el mismo lector.
- **JetSMART y SKY** ya se leen (la tabla dice "falta programar"). JetSMART alterna al azar una portada ligera sin tarifas: se relee una sola vez.
- **Urbania y Adondevivir: bloqueados.** Respondieron dos lecturas y luego el desafío antibots de Cloudflare ("Just a moment…", 403), también en la página 1 y en el otro dominio. No se usan ni se intenta evadirlo. Además son el mismo inventario: los ids de Adondevivir son los de Urbania desplazados unos pocos números. Los alquileres salen de **Infocasas** (ver abajo), que sí permite la lectura.
- **Neoauto: `<lastmod>` no sirve.** Todas las entradas de los mapas del sitio traen la misma fecha (la hora en que se generó el archivo). Los avisos nuevos se detectan por id y los precios se vuelven a leer por turnos, empezando por los más antiguos. El kilometraje (lo que Cowork no pudo leer) viene en los datos estructurados de cada aviso (`additionalProperty` → Kilometraje), junto con precio, moneda, marca, modelo, distrito y tipo de vendedor. Las páginas de modelo (`/venta-de-autos-<marca>-<modelo>`) no traen avisos en el HTML y las siguientes páginas de listados usan `?`, prohibido: no se usan.

---

## Revisión e integración · 17 de septiembre de 2026

- **Activos:** Rappi/Turbo (comida, 60 %); Falabella/Sodimac y ahora Promart, Oechsle, Estilos, Casaideas y Shopstar (hogar, 60 %); beneficios Diners y seguimiento histórico JetSMART/SKY desde Lima (viajes, 50 %). Se conservan los tres temas separados y los horarios existentes de 30 minutos. Las frecuencias de la tabla final son propuestas, no configuración aplicada.
- Se leyeron robots.txt y 50 productos reales de cada una de las cinco nuevas tiendas VTEX. Los catálogos respondieron y las reglas consultadas no excluyeron el endpoint. Cada ronda vuelve a verificar robots.txt; ante bloqueo se detiene esa fuente. Esto no sustituye los términos del sitio ni garantiza acceso futuro desde GitHub.
- VTEX revisa solo los primeros 50 productos ordenados por descuento de cada tienda, no todo su inventario. Filtra categorías de muebles, tecnología, electrodomésticos y hogar. No incluye ropa, alimentos ni belleza; los supermercados adicionales y Cuponatic siguen pendientes.
- Exige stock positivo, precio desde S/ 10, referencia mayor al precio y descuento calculado entre 60 % y menos de 95 %. Descarta referencias extremas hasta contar con verificación adicional. El precio tachado es el publicado por el vendedor, no un ahorro histórico demostrado.
- Deduplica ofertas VTEX con el mismo nombre y variante normalizados, vendedor, precio y condición, incluso entre plataformas. Puede no reconocer títulos escritos de forma diferente; no es una comparación universal de productos. Conserva el límite global de 24 ofertas en 8 mensajes de hogar por ronda y la memoria de 7 días.
- **Correcciones a la propuesta:** Falabella entrega precios en HTML con datos JSON integrados; no requiere navegador en nuestro lector. Diners sí respondió en nuestras pruebas y sigue activo. Robots.txt por sí solo no demuestra que LATAM, Ripley o Despegar sean accesibles: permanecen fuera por los bloqueos encontrados.
- Travelpayouts requiere registro/acceso y un token que aún no se ha proporcionado; no está activado. No se aplica la propuesta de avisar por bajadas del 25 %: el usuario fijó un mínimo del 50 % para viajes. No se añaden rutas, fechas ni referencias históricas inventadas.
- Las demás filas conservan las notas de investigación recibidas y necesitan validación propia antes de implementarse.

---

## Grupo 1 · Electrodomésticos, muebles y tecnología (`retail`)

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Promart | VTEX | Solo bloquea `/checkout*` | Verificado: árbol de categorías y orden por descuento |
| Oechsle | VTEX | Catálogo permitido | Verificado |
| Estilos | VTEX | Catálogo permitido | Verificado (ese día tenía un escritorio a -83 %) |
| Casaideas | VTEX | Catálogo permitido | Verificado (muebles y decoración) |
| Shopstar | VTEX | Catálogo permitido | Verificado |
| Plaza Vea, Wong, Metro | VTEX | Wong bloquea `/busca/*`; Plaza Vea solo `/checkout` | Verificado |
| Coolbox | HTML | Catálogo permitido; declara 21 sitemaps | Falta confirmar cómo entrega los precios |
| Juntoz | HTML | Bloquea cuenta, carrito y kiosko | Falta confirmar |
| Falabella | Navegador oculto | Bloquea carrito, cuenta, checkout y pedidos; el catálogo está permitido | Los precios se cargan con JavaScript |
| Ripley | HTML | Bloquea `/search/` y APIs de recomendaciones; las páginas de producto están permitidas y hay permiso explícito para bots de IA | Falta confirmar el formato de la página |
| Mercado Libre | API oficial | Exige registrar una aplicación y usar token | El acceso anónimo se cerró en 2025 |
| Sodimac | — | Zona gris: bloquea `/category/` y `/product/`, rutas que ya no coinciden con sus URLs actuales | Mejor usar Promart para lo mismo |
| Hiraoka | — | Responde 403 a cualquier lectura automática | No usar |

### Cómo se consulta una tienda VTEX (verificado)

```
# Los productos con mayor descuento de toda la tienda
https://<tienda>/api/catalog_system/pub/products/search?O=OrderByBestDiscountDESC&_from=0&_to=49

# Lo mismo dentro de una categoría
https://<tienda>/api/catalog_system/pub/products/search?fq=C:/<idCategoria>/&O=OrderByBestDiscountDESC&_from=0&_to=49

# Árbol de categorías (para conocer los ids)
https://<tienda>/api/catalog_system/pub/category/tree/2
```

- Campos que interesan: `productName`, `link`, y dentro de `items[].sellers[].commertialOffer`: `Price`, `ListPrice` y `AvailableQuantity`. Confirmar con una consulta real antes de programar.
- Máximo 50 productos por consulta (`_to` − `_from` ≤ 49).
- El orden por mejor descuento hace que baste **una consulta por tienda** para encontrar lo más rebajado: es la fuente más barata de todas.
- Trampas comprobadas:
  - `ListPrice` a veces está inflado o no existe. Descartar productos sin `ListPrice`.
  - Aparecen descuentos falsos del 95 % o más en productos de S/ 1 a S/ 5 (por ejemplo un marco LED a S/ 1 "antes S/ 71"). Conviene exigir un precio mínimo, por ejemplo S/ 10, y revisar con lupa lo que pase del 95 %.
  - Confirmar `AvailableQuantity > 0`.
  - Plaza Vea, Oechsle y Promart comparten marketplace, así que el mismo producto aparece en las tres. Hay que deduplicar por nombre y precio.

---

## Grupo 2 · Viajes, vuelos y hoteles (`viajes`)

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Travelpayouts (datos de Aviasales) | API oficial | Programa de afiliados: registro gratuito y solicitud de acceso | Verificado: usar los endpoints de muchos destinos por consulta, no los de ruta única |
| JetSmart | HTML (solo página de promociones) | Permite todo menos el motor de reservas | Falta programar |
| LATAM | HTML (solo página de promociones) | Permite el sitio general; bloquea compra, asientos y login. Publica un `llms.txt` (índice para agentes de IA) | Falta programar |
| SKY | HTML (solo página de promociones) | No publica `robots.txt`; su web es puro JavaScript | Falta programar |
| Despegar | HTML | Solo sus páginas de ofertas (`/vuelos-baratos`, `/paquetes/`, `/hoteles/h-*/`); bloquea buscador y APIs | Parcial |
| Civitatis, GetYourGuide, Viator | HTML | Páginas de tours permitidas; bloquean carrito y checkout | Falta programar |
| Booking.com | — | No deja leer ni su `robots.txt` | No usar |
| Diners Club Perú | — | Su web rechaza las lecturas automáticas (error 405) | No usar |

### API de Travelpayouts (verificado el 18 de septiembre de 2026)

El token va en la cabecera `X-Access-Token` (o como parámetro `token`) y se guarda como secreto, igual que `NTFY_TOPIC`.

Lo importante es **qué endpoint se usa**, porque hay dos familias y la diferencia decide si el grupo es viable:

```
# Una consulta, muchos destinos: la buena
https://api.travelpayouts.com/v1/city-directions?origin=LIM&currency=usd
https://api.travelpayouts.com/aviasales/v3/search_by_price_range?origin=LIM&price_max=500
https://api.travelpayouts.com/aviasales/v3/get_special_offers

# Una consulta, un mes entero de fechas de una ruta
https://api.travelpayouts.com/v2/prices/month-matrix?origin=LIM&destination=MAD&month=2026-12
https://api.travelpayouts.com/aviasales/v3/get_latest_prices?origin=LIM&destination=MAD

# Una consulta, una ruta y una fecha: la que hay que evitar como base del monitor
https://api.travelpayouts.com/v1/prices/cheap?origin=LIM&destination=MIA
```

Dos límites que hay que tener presentes:

- **Los datos son búsquedas de otros usuarios, guardadas 7 días.** No son tarifas en vivo. Una ruta que nadie buscó no tiene datos, y lo que hay puede ser de hace una semana. Sirven para **descubrir** candidatos, nunca como precio para reservar: todo aviso debe decirlo y llevar el enlace a la búsqueda en vivo.
- Hay límite de consultas por segundo (el calendario, por ejemplo, admite 10 por segundo).

### Por qué el "mínimo histórico" no sirve para vuelos

Fue la primera idea de este grupo y está mal para vuelos, por tres razones:

1. **El precio de un vuelo no es un número, es una combinación**: origen, destino, fecha de ida, fecha de vuelta y aerolínea. Una sola ruta con un año de fechas posibles y duraciones variables son decenas de miles de combinaciones. Guardar "el mínimo de la ruta" obliga a guardar un mínimo por combinación, y cubrir eso consulta por consulta revienta cualquier presupuesto.
2. **Mezcla cosas que no se comparan.** El mínimo histórico de una ruta pone en la misma bolsa un martes de temporada baja y un viernes 23 de diciembre. Es el mismo error que promediar precios de inmuebles por distrito en vez de por urbanización, y lo descartamos allá por la misma razón.
3. **La latencia no calza con el fenómeno.** Una oferta relámpago o una tarifa con error duran horas; la caché de la API tiene hasta 7 días.

Y una razón estratégica: para un viaje que ya se tiene decidido, **Google Flights ya hace seguimiento de precios gratis, con datos en vivo, avisos por correo e incluso la opción "cualquier fecha"** (verificado el 18 de septiembre de 2026). Programar eso otra vez no tiene sentido. Lo único que este monitor puede aportar de verdad es el caso contrario: **no tengo destino ni fecha, avísame cuando salir de Lima esté excepcionalmente barato**, sin que yo esté mirando.

### El método que sí conviene para vuelos

**1. Invertir la consulta.** En lugar de preguntar "¿cuánto cuesta Lima–Miami?" ruta por ruta, preguntar "¿a dónde se puede ir barato desde Lima?". Una sola consulta a `city-directions` devuelve muchos destinos con su precio. Solo los que pasen el filtro merecen una segunda consulta con `month-matrix` para ver el mes completo. Una ronda son unas 5 a 8 consultas en total, y cubre muchísimo más espacio que cien consultas ruta por ruta.

**2. Medir en centavos por kilómetro.** Es el equivalente del "año gratis" de los autos y de la rentabilidad de los inmuebles: una medida que se normaliza sola.

```
centavos por km = precio / distancia del trayecto
```

Con eso, US$ 380 a Madrid (unos 9.500 km) y US$ 380 a Bogotá (unos 1.900 km) dejan de parecerse: el primero es excelente y el segundo es caro. Ventajas:

- **Funciona desde la primera ronda, sin historia acumulada.** El mínimo histórico no dice nada durante semanas; esto dice algo de inmediato.
- Pone todos los destinos en una sola escala, que es justo lo que necesita quien no tiene destino fijo.
- Las coordenadas de los aeropuertos salen de un archivo público (OurAirports u OpenFlights) y la distancia es una fórmula: cero consultas, cero costo.

**No inventes las bandas de referencia.** El monitor debe calcular las suyas por tramo de distancia (regional, medio, intercontinental) con los datos que va juntando, y avisar cuando algo quede muy por debajo de la banda de su propio tramo. Y se repite la inversión de siempre: un valor absurdamente bajo casi nunca es un hallazgo, es un error de datos (moneda equivocada, un tramo simple contado como ida y vuelta, una tarifa fantasma).

**3. Dos niveles: vigía barato y confirmación puntual.** Las grandes ofertas de vuelos nacen de eventos identificables: campañas relámpago de aerolíneas, estrenos de ruta y tarifas con error. Leer las páginas de promociones de LATAM, SKY y JetSmart es barato y dice **cuándo** vale gastar consultas; recién entonces se consultan precios de esas rutas. Es la misma lógica que funcionó en Rappi: leer la señal que el sitio publica en vez de calcularlo todo.

**4. Lo que hay que descartar del diseño anterior**: consultar precios con navegador oculto en LATAM, SKY o JetSmart fecha por fecha. Una sesión completa de navegador para obtener un solo número es la forma más cara de conseguir el dato menos útil. Esos sitios se quedan solo como lectura de sus páginas de promociones, en HTML.

### Hoteles y tours

El arreglo de arriba es para vuelos. Para **tours** (Civitatis, GetYourGuide, Viator) el mínimo histórico sí funciona bien: un tour es un producto único con un precio, sin combinatoria de fechas, así que guardar su precio y avisar cuando baje es correcto. Los **hoteles** están en medio: tienen fechas, así que conviene compararlos contra su propia banda por mes, nunca contra un mínimo global.

---

## Grupo 3 · Restaurantes, comida y bazar (`comida`)

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Rappi | Navegador oculto + HTML | Ver README | Ya funcionando |
| Cuponatic Perú | HTML | Bloquea `/compra/`, `/comprar/`, `/cliente/`; el resto está permitido | Verificado: el HTML trae título, precio, precio normal y porcentaje |
| Plaza Vea, Wong, Metro | VTEX | Igual que en el grupo 1 | Verificado |
| Shopstar, Juntoz | VTEX / HTML | Igual que en el grupo 1 | Para bazar y hogar |
| PedidosYa | — | Bloquea con captcha | No usar |

### Cuponatic (verificado)

- Las ofertas aparecen en el HTML, sin necesidad de navegador.
- Patrón de URL: `https://www.cuponatic.com.pe/descuento/<nombre>?id_descuento=<número>`.
- El día de la prueba había, por ejemplo, entradas de cine a -61 % (S/ 10.90 contra S/ 27.80).

---

## Grupo 4 · Autos (`autos`)

Aquí no existe el "% de descuento": nadie publica un precio de lista de un auto usado. Lo que sí existe es un **precio de mercado**, y se puede calcular con los propios anuncios. La ganga es el aviso que está muy por debajo del precio de mercado de su mismo modelo, versión, año y kilometraje.

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Neoauto (usados, seminuevos y nuevos) | Mapa del sitio + HTML | `Disallow: /*?` para todos: **nunca usar direcciones con `?`**. Bloquea wget, HTTrack y descargadores masivos | Verificado: mapa del sitio y páginas de aviso |
| Derco | HTML | Sin ninguna restricción; declara 4 mapas del sitio | Verificado: publica "Precio lista" y el bono en el HTML |
| Autocosmos | HTML | Pausa obligatoria de 20 s y `/search` bloqueado. Bloquea rastreadores de IA (ClaudeBot, GPTBot y otros) | Verificado: su mapa del sitio es un catálogo de modelos vigentes, no de avisos |
| Hyundai Perú | HTML | Solo bloquea `/wp-admin/` | Verificado: su página de promociones no trae cifras, solo "consulta con tu concesionario" |
| Mercado Libre Perú | — | Su robots.txt no permite lectura automática; su API exige registrar una aplicación | No usar |
| Remates (SUNAT, REM@JU, VMC Subastas) | HTML | SUNAT no pide captcha y publica "precio de tasación"; VMC permite rastreadores comunes | No elegido; queda anotado por si algún día interesa |

### Neoauto: por qué es la fuente principal (verificado)

Una sola lectura del mapa del sitio entrega **todos** los avisos, y la estructura viene en la propia dirección:

```
https://neoauto.com/sitemap.xml
  └─ sitemap-avisos-autos.xml
       ├─ sitemap-avisos-autos-nuevos.xml       (~400 avisos)
       ├─ sitemap-avisos-autos-seminuevos.xml
       └─ sitemap-avisos-autos-usados.xml       (varios miles)
```

Cada entrada trae `<lastmod>`, y la dirección tiene esta forma:

```
https://neoauto.com/auto/usado/mitsubishi-montero-sport-2018-1869028
                    │         └ marca ─ modelo ─ versión ─ año ─ id
                    └ nuevo | usado
```

O sea: marca, modelo, versión, año e identificador **sin abrir una sola página**. Con eso cada ronda solo necesita leer los avisos nuevos o con `lastmod` distinto al de la ronda anterior. En marcha normal son una lectura del mapa y unas pocas páginas: es tan barato como el catálogo VTEX del grupo `retail`.

La página de cada aviso viene en HTML servido (no hace falta navegador) y trae:

- el precio (`US$ 21,900`) y, a veces, un descuento por financiar con un banco (`-US$1,000`);
- el distrito (Barranco, San Borja…);
- **cuánto lleva publicado** ("Publicado: hace más de un mes") y el número de visitas;
- el sello "Auto Verificado" cuando lo tiene;
- si el vendedor es concesionario o particular.

Queda una cosa por confirmar en la computadora del usuario, leyendo el HTML crudo: cómo vienen las especificaciones técnicas (kilometraje, transmisión, combustible). La sección existe, pero desde el entorno de la nube no se pudo leer. **El kilometraje es imprescindible para todo el método**, así que es lo primero que hay que resolver antes de programar lo demás.

### Derco: el único descuento publicado de verdad (verificado)

En sus páginas de catálogo, dentro del HTML, aparecen juntos:

```
Precio lista:  US$ 27,490
INCLUYE BONO $1,200   …   INCLUYE BONO $3,100
```

Un bono de $3,100 sobre US$ 27,490 es 11 %, y se calcula directo. Sus direcciones llevan `?brands=…&models=…`, permitido aquí porque el robots.txt de Derco no restringe nada. Ojo con no confundirse: en Neoauto las direcciones con `?` sí están prohibidas.

Advertencia que el aviso debe incluir: **el bono casi siempre está condicionado a financiar con un banco determinado**, no es un descuento en efectivo.

### El método de evaluación

1. **Reunir.** Guarda cada aviso en una memoria de precios: id, marca, modelo, versión, año, kilometraje, precio, moneda, distrito, tipo de vendedor, fecha de publicación y la lista de precios que ha tenido.
2. **Calcular el precio de mercado.** Para cada grupo (mismo modelo, misma versión, año ±1) usa la **mediana** de los avisos activos, nunca el promedio: un solo anuncio disparatado arruina un promedio. Dentro del grupo, corrige por kilometraje con una recta simple, o compara solo entre rangos de kilometraje parecidos.
3. **No opinar sin datos.** Si un grupo tiene menos de 8 comparables, no calcules nada: guarda y espera. Los primeros días el monitor solo acumula y no avisa; eso es lo correcto, no una falla.
4. **Medir.** `rebaja = (mediana − precio) / mediana`. Ese es el "% por debajo del mercado", el equivalente al descuento de Rappi.
5. **Decidir qué merece un aviso.** Esta es la parte delicada y tiene su propia sección más abajo ("Qué cuenta como súper oferta"). El resumen: el porcentaje bajo la mediana no sirve como criterio principal. Para los autos nuevos, que sí son productos casi idénticos, alcanza un margen chico: avisa desde 8 % bajo la mediana del mismo modelo y año (🚨 desde 12 %), y desde un bono de 10 % sobre el precio lista en Derco (🚨 desde 15 %).

6. **La bajada de precio: la señal más barata y la más útil.** Como el monitor vuelve a pasar por los mismos avisos, compara con el precio anterior. Una baja de 10 % o más —y sobre todo la segunda baja— en un aviso que ya lleva semanas publicado es un vendedor apurado. Para el uso que se le va a dar (tener presentes las buenas oportunidades, sin apuro de comprar) esta señal vale más que cualquier cálculo, y no necesita comparables: funciona desde la segunda ronda.
7. **Ancla opcional.** El catálogo de Autocosmos da el precio de lista de los modelos que aún se venden nuevos. Con eso se puede calcular qué porcentaje de su precio original conserva un usado, y detectar el que conserva mucho menos que sus pares del mismo año.

### Qué cuenta como súper oferta (leer antes de programar los umbrales)

El error natural es pensar que la mejor oferta es la más barata respecto del mercado. Con autos es al revés: **mientras más grande es la rebaja, más probable es que la causa sea un defecto y no una oportunidad.** Por debajo de cierto punto ya no se está midiendo precio, se está midiendo problemas. Así que el porcentaje sirve como filtro, nunca como criterio principal, y la señal debe **saturarse y luego invertirse**: entre 18 % y 32 % bajo los comparables suma puntos; pasado el 35 % empieza a restar.

El criterio principal es otro, y es el que hay que programar:

#### 1. El año gratis (criterio principal)

En lugar de un porcentaje inventado, se usa la escalera de precios del propio modelo, que el monitor ya tiene:

```
mediana(modelo, 2022) = US$ 20,000
mediana(modelo, 2021) = US$ 17,000
aviso: modelo 2022 a US$ 17,200   →  te llevas un año de depreciación gratis
```

La regla: **`precio del aviso ≤ mediana del mismo modelo del año anterior`**.

Por qué es mejor que un porcentaje: se ajusta solo (funciona igual en un Yaris de US$ 8.000 y en un Prado de US$ 45.000), no hay número que calibrar, se explica en una frase y no depende de nada que el vendedor diga. Y viene graduado:

| Resultado | Lectura |
|---|---|
| Paga el precio del año anterior | Buena oportunidad |
| Paga el precio de dos años antes | Excepcional, avisar 🚨 |
| Paga menos que tres años antes | Sospechoso: hay una razón oculta, revisar antes de emocionarse |

Necesita al menos 8 comparables en el año del aviso **y** 8 en el año anterior. Si falta uno de los dos, no se puede calcular y no se avisa.

#### 2. Retención relativa: el auto bueno al precio del auto malo

Con los precios de autos nuevos (Neoauto trae ~400 avisos nuevos, y Autocosmos el catálogo de modelos vigentes) se calcula, por modelo y año:

```
retención = mediana del usado / precio del mismo modelo nuevo
```

Los modelos se separan solos en dos familias: los que conservan valor y los que se caen. La súper oferta es **un modelo de alta retención ofrecido al precio de uno de baja retención**. Eso es una anomalía respecto de su clase, no un porcentaje absoluto, y es lo más cercano a "excelentísima opción" que se puede calcular: no dice que esté barato, dice que está barato *para lo que es*.

#### 3. Una sola anomalía

El principio que más basura descarta: **una ganga de verdad es aburrida en todo menos en el precio.** Las trampas son raras en varias cosas a la vez — precio bajísimo *y* kilometraje imposible *y* versión que no corresponde *y* descripción escueta *y* vendedor sin historial.

Así que el monitor cuenta anomalías y exige **exactamente una**: el precio. Si hay dos o más, no se avisa como oferta. Cuentan como anomalía: kilometraje fuera del rango de 5.000 a 25.000 km por año, versión que no calza con el nivel de precio, datos incompletos, moneda dudosa, o cualquiera de las palabras de la lista de abajo.

#### 4. La antigüedad del aviso es evidencia a favor, no en contra

Al revés de lo que haría un comprador apurado: un aviso que lleva 45 días o más publicado, con una o dos bajadas de precio y las mismas especificaciones desde el principio, es prueba de que el auto existe y el vendedor es real. Las estafas son recientes y desaparecen rápido. Neoauto publica "Publicado: hace más de un mes", así que esto sale gratis.

#### 5. Historial del anunciante (verificado el 17 de septiembre de 2026)

Neoauto publica las páginas de sus 58 concesionarios registrados:

```
https://neoauto.com/sitemap-anunciantes.xml
  └─ sitemap-anunciantes-revendedores.xml   (58 páginas, una por concesionario)
       └─ https://neoauto.com/<nombre-del-concesionario>
```

Cada página lista su inventario completo con precios y dice cuántos avisos tiene ("12 de 49 avisos"). Con eso se responde la pregunta que de verdad importa: **¿los otros autos de este vendedor están a precio de mercado?**

- Sí, y este uno está 25 % abajo → oportunidad real (liquidación, stock del año, una parte de pago que quieren sacar).
- Todos sus autos están "baratos" → no es un descuento, es un precio de gancho o un vendedor de autos con problemas.

Entre esos 58 hay canales de liquidación que conviene leer directo, por ejemplo `neoauto.com/dercocenter-liquidacion`, donde los avisos dicen "Auto Nuevo con precio de Outlet Derco Center".

Para vendedores particulares no hay historial disponible: ahí la confianza tiene que venir de los puntos 3 y 4.

#### 6. Puntaje en lugar de umbral

Reúne todo en un puntaje de 0 a 100 y avisa solo desde 70. Sugerencia de pesos:

| Señal | Puntos |
|---|---|
| Año gratis (uno = 20, dos = 35) | 35 |
| Precio contra comparables, saturando en 30 % y restando pasado el 35 % | 20 |
| Retención alta a precio de retención baja | 20 |
| Anunciante con historial y resto del inventario a precio de mercado | 15 |
| Bajadas de precio y semanas publicado | 10 |

Antes del puntaje, la parte eliminatoria: mínimo 8 comparables, moneda normalizada, una sola anomalía, ninguna palabra de la lista negra, y precio por encima del 55 % de la mediana. Lo que no pase esto no entra al puntaje, sin importar cuán barato esté.

#### Lo que este método nunca va a saber

Estado mecánico, si estuvo chocado, cuántos dueños tuvo de verdad, si las fotos esconden algo. Nada de eso se publica. Por lo tanto el aviso dice **"candidato estadísticamente excelente"**, nunca "buen auto", y la revisión de cinco minutos con la placa sigue siendo obligatoria antes de cualquier decisión.

### Los filtros que separan una ganga de una trampa

Sin estos filtros el monitor avisa basura. Todos son obligatorios:

- **Demasiado barato es mala señal.** Por debajo del 55 % de la mediana casi nunca es ganga: es estafa, auto siniestrado, "con detalle" o precio de gancho. Va en una lista aparte, marcado como sospechoso, nunca como oferta.
- **Moneda.** En Perú se publica en dólares y en soles. Si no se normaliza, un auto en soles parece 70 % más barato que el mismo auto en dólares: es la causa número uno de falsas gangas. Normaliza todo a una sola moneda con un tipo de cambio configurable.
- **Palabras de la descripción** que descartan o marcan el aviso: choque, chocado, siniestrado, para reparar, con detalle, no camina, motor malogrado, papeles en trámite, sin SOAT, deuda, prenda, gravamen, GLP, GNV, importado usado, a nombre de tercero, permuta.
- **Kilometraje inverosímil.** Muy bajo para el año (menos de unos 5.000 km por año) es sospechoso, no una virtud: el kilometraje se puede regresar.
- **Versión.** Comparar una versión base contra una full da rebajas falsas. Agrupa por versión cuando haya comparables suficientes; si no, agrupa por modelo y año y exige más margen.
- **Duplicados.** El mismo auto reaparece con otro id, o lo publican varios vendedores. Deduplica por modelo, versión, año, kilometraje y precio.

### Comprobar antes de creerle a una oferta

Los avisos casi nunca traen la placa, así que esta parte se hace a mano después de contactar al vendedor y toma cinco minutos. El aviso solo tiene que recordarlo y dejar el enlace:

- Consulta vehicular de SUNARP, oficial y gratuita: https://consultavehicular.sunarp.gob.pe/consulta-vehicular (titulares y características del vehículo).
- Papeletas, deudas y récord de siniestros se consultan por placa en las páginas oficiales correspondientes.

**No automatizar estas consultas.** Son formularios del Estado con validación contra robots y no se evade. Van como enlace dentro del aviso, para que el usuario los abra.

### Ritmo y volumen

Como no hay apuro de comprar, conviene poco y bueno:

- Una ronda cada 6 horas alcanza de sobra.
- Máximo 3 avisos por ronda, y no repetir el mismo auto antes de una semana (eso ya lo hace `REPETIR_AVISO_HORAS`).
- Un resumen semanal con las 5 mejores oportunidades es más útil que avisos sueltos.

---

## Grupo 5 · Inmuebles (`inmuebles`)

Un inmueble no es comparable con otro como sí lo son dos autos del mismo modelo: dos departamentos de tres dormitorios en Surco pueden valer muy distinto por el piso, la vista, la antigüedad del edificio, el mantenimiento o media cuadra de diferencia. Por eso la mediana de comparables, que en autos funciona bien, aquí es débil.

Pero los inmuebles tienen algo que los autos no: **un ingreso observable**. Los mismos portales publican ventas y alquileres, así que se puede calcular cuánto renta un inmueble y compararlo con lo que renta su zona. Ese es el criterio central de este grupo.

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Urbania | HTML | **Permite `?sort=low_price`** y las páginas 2 a 5. Prohíbe `/avisos-api/`, `/users-api/`, `/leads-api/` y bloquea por nombre a Scrapy, wget y HTTrack | Verificado |
| Adondevivir | HTML | Permite `/*-ordenado-por-precio-ascendente*` y las páginas 2 a 5. Mismas APIs prohibidas | Verificado |
| Nexo Inmobiliario (proyectos en preventa) | HTML | `Disallow:` vacío: permite todo | Verificado |
| Scotiabank, inmuebles adjudicados | PDF mensual | Documento público | Verificado: ~242 inmuebles con distrito, área, valor referencial y estado registral |
| Remates judiciales (REM@JU) y SUNAT | HTML | SUNAT no pide captcha ni registro | Verificado: SUNAT publica "Precio de tasación" y fecha de remate |
| Infocasas | HTML | Usa la lista "bad bot blocker" con más de mil agentes bloqueados; para un lector común solo prohíbe rutas internas | Zona gris: sirve como segunda opinión, a baja frecuencia, y hay que leer sus reglas exactas antes de usarlo |
| Properati | — | Responde 403 a cualquier lectura automática | No usar |

### Lo que los portales permiten expresamente (verificado)

Urbania y Adondevivir son del mismo grupo y los dos dejan pedir **el orden por precio más bajo**, que es justo lo que necesita un buscador de oportunidades:

```
Urbania:      Allow: ?sort=low_price          (y Disallow: ?sort=* para el resto)
Adondevivir:  Allow: /*-ordenado-por-precio-ascendente*
Los dos:      páginas 2 a 5 permitidas, de la 6 en adelante prohibidas
```

Es el equivalente al `OrderByBestDiscountDESC` del grupo `retail`: una consulta por combinación de distrito, tipo y operación trae lo más barato primero. Con unos diez distritos, dos tipos y las dos operaciones (venta y alquiler) son unas 40 consultas por ronda, de sobra dentro del presupuesto.

**Los dos prohíben sus APIs internas** (`/avisos-api/`, `/users-api/`, `/leads-api/`). Es la tentación obvia al programar, porque devuelven JSON limpio: no se usan. Solo HTML y mapas del sitio.

### El criterio: rentabilidad contra la de su propia zona

```
rentabilidad bruta = (alquiler mensual de comparables × 12) / precio de venta
```

Por qué este criterio y no el precio por m²:

- **Se ajusta solo.** No hay porcentaje que calibrar; sirve igual para un estudio en Barranco y una casa en La Molina.
- **El alquiler ya cobra la calidad.** Piso, vista, edificio nuevo o viejo, ascensor, seguridad: todo eso ya está dentro del alquiler que el mercado paga. Comparar rentabilidades corrige por calidad, cosa que el precio por m² no hace.
- **Los dos lados se observan en el mismo portal**, con el mismo permiso de lectura y el mismo orden por precio.

En Lima la rentabilidad bruta suele moverse entre 5 % y 7 % anual. La regla:

| Rentabilidad implícita frente a la de su zona | Lectura |
|---|---|
| 1,3 veces la de su zona (por ejemplo 8 % donde el resto rinde 6 %) | Vale mirarlo |
| 1,5 veces | Excepcional, avisar 🚨 |
| Más de 2 veces | No es ganga, es advertencia: el alquiler de referencia está mal, el inmueble no se puede alquilar o hay un problema legal |

Se repite la misma inversión que en autos: pasado cierto punto, el número dejó de medir precio y empezó a medir problemas.

Necesita al menos 8 ventas y 8 alquileres comparables en la misma micro-zona, mismo tipo y rango de área parecido. Si falta uno de los dos lados, no se calcula.

### Micro-zona, nunca distrito

Es el error que arruinaría todo el grupo. Los distritos de Lima son demasiado heterogéneos: Surco va de Chacarilla a Higuereta, Miraflores del malecón a Angamos, y las medianas por distrito mezclan cosas que no se parecen. La unidad tiene que ser la urbanización o el barrio que el propio aviso declara, o una cuadrícula armada con las coordenadas del aviso. Sin micro-zona, los resultados son basura con apariencia de estadística.

### Precio por m², como segundo criterio

Útil sobre todo si algún día el interés pasa de inversión a vivienda propia, donde la rentabilidad importa menos. Dos condiciones inflexibles: **nunca mezclar m² de terreno con m² construidos ni con m² techados** en la misma mediana, y revisar que el área sea verosímil (es común que escriban 1.200 m² donde eran 120).

### Remates judiciales: el único descuento definido por ley (verificado)

Es la parte más interesante de este grupo, porque el descuento no lo declara un vendedor: lo fija el Código Procesal Civil.

- **Artículo 736**: la base del remate es **dos terceras partes del valor de tasación**, y no se admite oferta menor. O sea que arranca 33 % por debajo de la tasación oficial.
- **Artículo 742**: si no hay postores, cada nueva convocatoria baja la base **15 % respecto de la anterior**, tantas veces como sea necesario.

Eso da una escalera calculable:

| Convocatoria | Base respecto de la tasación | Descuento |
|---|---|---|
| Primera | 66,7 % | 33 % |
| Segunda | 56,7 % | 43 % |
| Tercera | 48,2 % | 52 % |
| Cuarta | 41,0 % | 59 % |

El monitor sigue el mismo expediente entre convocatorias y el número de convocatoria le dice exactamente cuán profundo es el descuento, sin estimar nada.

Y aquí vuelve la inversión, más fuerte que en autos: **un inmueble que llegó a la cuarta o quinta convocatoria sin postores casi siempre tiene un problema** (está ocupado, tiene litigio, no tiene acceso independiente, la tasación estaba inflada). Un inmueble bien ubicado en primera o segunda convocatoria es mucho más interesante que uno barato en la quinta. Prioriza por convocatoria baja, no por descuento alto.

### Adjudicados de bancos (verificado)

Scotiabank publica un PDF mensual con unos 242 inmuebles. Columnas útiles: dirección, tipo, departamento, provincia, distrito, **valor referencial en dólares, área y estado registral** (marca cuáles están `INSCRITO`). Con el área y el valor sale el precio por m² directo, comparable contra la mediana del portal para esa micro-zona.

```
https://cdn.aglty.io/scotiabank-peru/PDFs/acerca-de/venta-de-inmuebles-y-muebles-adjudicados/listado-venta-inmuebles.pdf
```

Dos cosas que el documento mismo advierte y el aviso debe repetir: los precios son **referenciales y sujetos a la valorización final**, y conviene mirar el estado registral antes que el precio. Banco Pichincha y Banco GNB publican listas equivalentes; vale revisarlas igual.

La forma de usarlo es comparar el PDF de este mes con el del mes pasado: lo nuevo y lo que bajó de precio es la señal.

### Preventa

Nexo Inmobiliario (permite todo en su robots.txt) lista proyectos en construcción. El precio de preventa está estructuralmente por debajo del de una unidad terminada en la misma zona, así que la comparación es precio por m² de preventa contra la mediana de terminados de esa micro-zona. El costo de ese descuento es el riesgo de obra y la espera, y el aviso tiene que decirlo.

### Los filtros: aquí importan más que en autos

Porque lo que se pierde es mucho mayor. Descartan o marcan el aviso:

- **Lo que no es propiedad plena**: "derechos y acciones" (se compra una fracción, no el inmueble, y parece 60 % más barato), "aires", "posesión", "certificado de posesión", "sin título", "sin saneamiento", "en trámite de independización", "sucesión intestada", "anticresis", "usufructo", "bien futuro".
- **Ocupado**: la trampa clásica de los remates. "Ocupado", "con posesionarios", "desocupación a cargo del comprador". El precio es bajo porque el comprador hereda un juicio de desalojo que puede tomar años.
- **Cargas y gravámenes**: hipoteca vigente, embargo, medida cautelar.
- **Mantenimiento alto**: un departamento barato con cuota de US$ 400 al mes no es barato. Si el aviso declara el mantenimiento, réstalo del cálculo de rentabilidad.
- **Antigüedad del edificio**: lo construido antes de 1997 quedó fuera de la norma sísmica E.030 vigente y se transa más bajo por una razón real. Un edificio de los años sesenta a precio de ganga en zona de suelo blando no es una oportunidad. Si el aviso declara antigüedad, úsala; si no, márcalo como dato faltante.
- **Área inverosímil** y confusión entre terreno, construido y techado.
- **Duplicados**: el mismo inmueble publicado por varias inmobiliarias y republicado con otro id. Deduplica por micro-zona, área, dormitorios y precio.

### Comprobación que no se automatiza

Antes de cualquier decisión, y a mano:

- **Partida registral en SUNARP** (publicidad registral): confirma quién es el titular, el área inscrita y si hay cargas o gravámenes. Es el paso que no se puede omitir.
- **Parámetros urbanísticos** en la municipalidad del distrito, si interesa construir o ampliar.
- **Deuda de predial y arbitrios** del inmueble, que se hereda en la práctica.

Son trámites con validación contra robots o de pago. El aviso deja el enlace y el recordatorio; el monitor no los consulta.

### Ritmo y volumen

- Una ronda cada 12 horas para los portales: el mercado inmobiliario se mueve en meses, no en horas.
- Los remates y el PDF de adjudicados, una vez al día y una vez por semana respectivamente.
- Máximo 3 avisos por ronda y un resumen semanal. Igual que en autos: pocas y buenas.

---

## Frecuencias sugeridas

| Grupo | Cada cuánto | Por qué |
|---|---|---|
| `comida` | 30 minutos | Las ofertas relámpago duran poco |
| `retail` | 3 horas | Los precios cambian por día, no por minuto |
| `viajes` | 6 horas | Cuidar la cuota de la API y no saturar |
| `autos` | 6 horas | No hay apuro: lo que importa es no perderse la oportunidad, no verla primero |
| `inmuebles` | 12 horas | El mercado se mueve en meses; los remates una vez al día |

---

## Implementación de vuelos · 17 de septiembre de 2026

`monitor/flights.py` lee JetSMART en https://www.jetsmart.com/pe/es/ (`let list = JSON.parse(...)`, sin ejecutar JS) y SKY en https://www.skyairline.com/flights/es-pe/ofertas-descuentos (`__NEXT_DATA__`, Apollo StandardFareModule.fares). La página `/pe/es/minisitios/promo` de JetSMART respondió pero no incluía tarifas, por eso no se usa.

Se leyeron robots.txt y cuerpos completos públicos de ambas fuentes. JetSMART publica reglas que no excluyen la portada. SKY devuelve su portada HTML en /robots.txt, sin directivas: no se presenta esto como permiso explícito; se continúa solo con su página pública de ofertas. Si aparecen directivas, se respetan; una respuesta desconocida o un bloqueo detiene la fuente. Cada ronda usa dos lecturas por aerolínea (robots.txt y la página) separadas por 1,5 segundos; si la página llega sin catálogo se relee una sola vez, porque JetSMART alterna al azar una portada ligera sin el carrusel de tarifas. Si la relectura tampoco trae catálogo, se marca error. No sigue enlaces al motor de reservas. JetSMART: `pi.pen` con tasas, comprobado contra `p.pen + i.pen`, salida `dep=LIM`, fecha/hora `date`, número `fn`, clase `c`, plazas `s>0`. SKY: `totalPrice` en su moneda, con el aviso público `+ tasas`, `originAirportCode=LIM`, solo ida y fecha futura; ignora precios vistos hace más de 24 horas. No se interpreta `totalPrice` como total final con impuestos.

El usuario autorizó caídas >=50 % con historial comparable. Se compara contra el mínimo de los 30 días anteriores con al menos tres días distintos de observaciones, excluyendo el día actual (UTC). No se inventa historial inicial. La memoria viaja en state/viajes.json y los avisos al tema existente de viajes. SKY permite comparar mínimos publicados por fecha, no garantiza mismo vuelo ni equipaje. Los formatos cambiados generan error visible; cero alertas con historial insuficiente es normal.

## Conveniencia y supermercados · revisión del 17/18 de septiembre de 2026

- **Tambo activo:** https://www.tambo.pe/pedir, datos JSON públicos en window.__remixContext, menuData.products. 79 productos en la muestra. availabilityAt.finalPrice/basePrice, available y visible. Precios por pack/presentación, cobertura por confirmar; no se ingresa dirección ni sesión.
- **Makro activo:** catálogo VTEX de https://makro.plazavea.com.pe (enlazado por Makro). La consulta pidió hasta 50 productos ordenados por descuento y devolvió solo 10; cobertura parcial, no inventario completo. Stock positivo y comparación Price/ListPrice. Respeta presentaciones mayoristas y pide confirmar mínimos y disponibilidad en Lima. Excluye electrodomésticos, tecnología y muebles de este tema.
- Ambos verifican robots.txt en cada ronda, calculan >=60 % sin redondear al alza y descartan referencias extremas >=95 %. No se exige S/10 mínimo a alimentos. Ninguna oferta alcanzó 60 % en la muestra de evaluación. Se ejecutan en catalogos.yml cada 30 minutos y usan NTFY_TOPIC (grupo original de comida/bazar), con memoria independiente state/comida.json y deduplicación de siete días. No deduplica una misma promoción entre Rappi y la tienda directa, porque son canales/condiciones distintos.
- **Mass pendiente:** https://catalogos.tiendasmass.com.pe respondió, pero solo expuso estructura de página, sin catálogo verificable de precios anteriores/actuales. robots.txt respondió 404. No se activa una fuente que siempre devuelva cero sin leer productos.
- **Listo pendiente:** https://www.primax.com/nosotros/tiendas/ enlaza un encarte PDF de septiembre/octubre de 2026. No se ha validado un lector por producto, vigencia y precio anterior. No está activo; tampoco se tratan sorteos, puntos o sellos como descuentos.
- **Formato ntfy móvil:** producto, precio/descuento y referencia en líneas separadas; bloques separados por espacio (y separador en los lotes). No se insertan marcas Markdown que la app pueda mostrar literalmente. La documentación de ntfy limita el renderizado Markdown a la web: https://docs.ntfy.sh/publish/#markdown-formatting.

## Implementación de vuelos por distancia, autos e inmuebles · 18 de septiembre de 2026

**Vuelos (centavos por km).** Cada tarifa JetSMART/SKY desde Lima se mide en centavos por kilómetro. La distancia sale de `monitor/datos/aeropuertos.csv` (4.377 códigos: aeropuertos con vuelos regulares de OurAirports, dominio público, más los códigos de ciudad de Travelpayouts como `BUE` o `SAO`, de su archivo público `data/en/cities.json`). Las bandas se separan por fuente, moneda y tramo (nacional < 1.200 km, regional < 4.000, medio < 8.000, largo), se calculan con lo que el propio monitor observa en 30 días y exigen 20 tarifas distintas antes de opinar. Avisa desde 50 % bajo la mediana del tramo (el mínimo que eligió el usuario para viajes) y descarta lo que quede bajo el 20 % de la mediana, porque casi siempre es un error de datos. Si una tarifa ya avisó por caída histórica, no se repite por distancia. El aviso dice que es una medida por km, no un descuento anunciado.

**Travelpayouts.** Programado con los campos de su documentación y probado en vivo el 18 de septiembre con el token del usuario: `city-directions` devolvió 29 destinos desde Lima (`departure_at` trae zona horaria `-05:00`) y la ronda de GitHub también. `v1/city-directions?origin=LIM&currency=usd` (una consulta, muchos destinos; precios de ida y vuelta cuando traen `return_at`, así que se divide por el doble de la distancia) y, para un máximo de 3 candidatos, `v2/prices/month-matrix` para listar otras salidas del mes con precio parecido. El token va en la cabecera `X-Access-Token`, nunca en la dirección ni en los registros. Una lectura cada 6 horas aunque el grupo corra cada 30 minutos. Todo aviso dice que son búsquedas guardadas hasta 7 días y enlaza la búsqueda en vivo de Aviasales.

**Autos (Neoauto).** Cada 6 horas: robots.txt, los tres mapas del sitio (~4.000 avisos) y hasta 150 páginas de aviso (`LECTURAS_AUTOS`), primero las nuevas. Con ~4.000 avisos el primer recorrido completo tarda unos 7 días; después cada precio se relee cada ~7 días. Memoria en `state/autos.json`: precio y fecha de cada cambio, primera vez visto, kilometraje, versión, distrito y tipo de vendedor. **No se guardan nombres ni teléfonos de particulares**; de las empresas, solo su nombre comercial para el historial del anunciante. Lo implementado del método:

- Filtros eliminatorios: palabras de la lista negra, kilometraje fuera de 5.000–25.000 km por año o no informado, precio bajo el 55 % de la mediana, más barato que la mediana de tres años antes, y un vendedor cuyo inventario entero está bajo el mercado.
- Bajada de precio de 10 % o más en un aviso con un mes publicado: funciona sin comparables.
- Año gratis con 8 comparables en el año del aviso y 8 en el anterior (medianas en dólares con `TIPO_CAMBIO`, 3,5 por defecto) y puntaje desde 70. La retención relativa todavía no se calcula, así que el puntaje se escala sobre las señales disponibles (35 + 20 + 15 + 10 = 80). Con esa escala, un año gratis de un particular no llega a 70: hace falta el segundo año gratis o el respaldo del historial del concesionario.
- Autos nuevos: 8 % bajo la mediana del mismo modelo, versión y año (🚨 desde 12 %).
- Máximo 3 avisos por ronda; el mismo aviso y precio no se repite en 60 días.
- Pendiente: Derco (bono sobre precio de lista), retención relativa, canales de liquidación y resumen semanal.

**Inmuebles.** Nexo Inmobiliario: robots.txt permite todo; 739 proyectos en `sitemap-proyectos.xml` (731 de departamentos). Cada proyecto trae su ficha schema.org, coordenadas y modelos con precio, área y dormitorios. Se leen 60 proyectos cada 12 horas (`LECTURAS_INMUEBLES`; recorrido completo en ~6 días). La micro-zona es un radio de 1,5 km alrededor del proyecto, nunca el distrito. Avisa si su precio mediano por m² queda entre 23 % y 50 % bajo la mediana de al menos 8 proyectos cercanos (23 % equivale a la rentabilidad 1,3 veces la de la zona; 33 % o más lleva 🚨; más de 50 % se trata como error de área o moneda) o si un modelo baja 10 % frente a su primer precio. Compara preventa contra preventa, no contra terminados: los terminados vendrían de los portales bloqueados.

Scotiabank: el PDF (242 filas) se lee una vez por semana con `pypdf`. La primera lectura solo guarda la lista; después avisa lo nuevo y lo que bajó 10 % o más, solo en Lima y Callao, con estado registral `INSCRITO` y sin "ACC" (acciones y derechos) ni las palabras de los filtros. Cuidado al leer el estado: "TERRENO URBANO INSCRITO" termina en las letras "NO INSCRITO", así que se compara la palabra completa.

**Infocasas (añadido el 18 de septiembre por la tarde).** Se revisaron las alternativas de alquileres: RE/MAX Perú responde 403 de Cloudflare incluso a su robots.txt (no se usa); Century 21 Perú (`century21.pe`) permite leer sus fichas y publica un mapa del sitio con todas sus propiedades, pero hay que abrir una página por inmueble (queda como ampliación posible); **Infocasas** permite los listados y trae en la propia página (`__NEXT_DATA__` → `fetchResult.searchFast`) 21 avisos por página con precio en su moneda y en dólares (`price_amount_usd`, con el tipo de cambio del sitio), m² construidos, coordenadas, barrio, mantenimiento (`commonExpenses`), dormitorios y descripción. Tiene una ruta permitida `/<venta|alquiler>/<departamentos|casas>/lima/<distrito>/publicado-ultimos-30-dias` (y `/paginaN`), que evita los miles de avisos viejos que el sitio conserva (muchos con fecha de 2020 a 2024). Su robots.txt solo prohíbe combinaciones `-y-` y rutas internas; seis lecturas seguidas, luego treinta, no tuvieron ningún bloqueo.

Cómo se usa: 172 búsquedas (43 distritos de Lima Metropolitana, sin el Callao × departamentos/casas × venta/alquiler) leídas por turnos, 60 páginas cada 6 horas (`PAGINAS_INFOCASAS`); la mayoría tiene una sola página, así que el recorrido completo tarda uno o dos días. Memoria de 120 días en `state/inmuebles.json`, sin descripciones ni datos de contacto: solo las palabras de alerta encontradas. Criterio del diseño de Cowork: alquiler estimado = mediana de US$/m² de al menos 8 alquileres a 1,5 km y de 70 % a 140 % del área, menos el mantenimiento declarado; rentabilidad implícita frente a la de la zona (mediana de alquiler por m² × 12 / mediana de venta por m² de al menos 8 ventas cercanas del mismo tamaño). Avisa de 1,3 a 2 veces la de la zona (🚨 desde 1,5); más de 2 veces es advertencia, no oferta. También avisa si una venta baja 10 %. Se descartan avisos con precio imposible para su operación (una «venta» de US$ 900 o un alquiler de más de US$ 60/m²). La prueba con 30 páginas reales dio una rentabilidad típica de zona de 4,7 % en Miraflores y un candidato: 75 m² a US$ 130.000, 6,7 % frente a 4,5 %.

Nota honesta: como el alquiler se estima con la mediana por m² de la zona, la comparación de rentabilidades equivale en buena parte a comparar precio por m², corregido por el mantenimiento. Lo que agrega es la cifra de rentabilidad bruta, útil para decidir. Solo mejoraría con el alquiler real de ese mismo inmueble, que no existe.

Sin el secreto del tema, `autos` e `inmuebles` igual corren y guardan memoria (las primeras semanas solo juntan comparables), pero no envían nada ni marcan error. Pendiente: remates judiciales (REMAJU/SUNAT), Pichincha y GNB, e Infocasas (zona gris).
