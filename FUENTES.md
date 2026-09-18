# Fuentes de ofertas en Perú

Guía de los sitios que se pueden vigilar, ordenados en tres grupos. La lista original recibida es una propuesta de investigación; sus afirmaciones no equivalen a integración ni a cobertura comprobada. La revisión de implementación siguiente indica qué se comprobó realmente.


## Revisión e integración · 17 de septiembre de 2026

- **Activos:** Rappi/Turbo (comida, 60 %); Falabella/Sodimac y ahora Promart, Oechsle, Estilos, Casaideas y Shopstar (hogar, 60 %); beneficios Diners y seguimiento histórico JetSMART/SKY desde Lima (viajes, 50 %). Se conservan los tres temas separados y los horarios existentes de 30 minutos. Las frecuencias de la tabla final son propuestas, no configuración aplicada.
- Se leyeron robots.txt y 50 productos reales de cada una de las cinco nuevas tiendas VTEX. Los catálogos respondieron y las reglas consultadas no excluyeron el endpoint. Cada ronda vuelve a verificar robots.txt; ante bloqueo se detiene esa fuente. Esto no sustituye los términos del sitio ni garantiza acceso futuro desde GitHub.
- VTEX revisa solo los primeros 50 productos ordenados por descuento de cada tienda, no todo su inventario. Filtra categorías de muebles, tecnología, electrodomésticos y hogar. No incluye ropa, alimentos ni belleza; los supermercados adicionales y Cuponatic siguen pendientes.
- Exige stock positivo, precio desde S/ 10, referencia mayor al precio y descuento calculado entre 60 % y menos de 95 %. Descarta referencias extremas hasta contar con verificación adicional. El precio tachado es el publicado por el vendedor, no un ahorro histórico demostrado.
- Deduplica ofertas VTEX con el mismo nombre y variante normalizados, vendedor, precio y condición, incluso entre plataformas. Puede no reconocer títulos escritos de forma diferente; no es una comparación universal de productos. Conserva el límite global de 24 ofertas en 8 mensajes de hogar por ronda y la memoria de 7 días.
- **Correcciones a la propuesta:** Falabella entrega precios en HTML con datos JSON integrados; no requiere navegador en nuestro lector. Diners sí respondió en nuestras pruebas y sigue activo. Robots.txt por sí solo no demuestra que LATAM, Ripley o Despegar sean accesibles: permanecen fuera por los bloqueos encontrados.
- Travelpayouts requiere registro/acceso y un token que aún no se ha proporcionado; no está activado. No se aplica la propuesta de avisar por bajadas del 25 %: el usuario fijó un mínimo del 50 % para viajes. No se añaden rutas, fechas ni referencias históricas inventadas.
- Las demás filas conservan las notas de investigación recibidas y necesitan validación propia antes de implementarse.

Cómo leer la tabla:

- **Permiso**: lo que el sitio declara en su `robots.txt`. No reemplaza a sus términos de uso, que pueden decir otra cosa y cambian sin aviso.
- **Vía**: cómo se obtienen los datos, de más fácil a más difícil: API oficial → catálogo VTEX → HTML → navegador oculto (Playwright).

Reglas que valen para todas las fuentes: al menos 1 segundo entre consultas, sin iniciar sesión, sin comprar nada, cortar la ronda si el sitio responde 403 o 429, y nunca evadir captchas.

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
- Una consulta obtiene una muestra de 50 productos ordenados por descuento. No garantiza encontrar todas las ofertas ni las mejores por cada categoría.
- Trampas comprobadas:
  - `ListPrice` a veces está inflado o no existe. Descartar productos sin `ListPrice`.
  - Aparecen descuentos falsos del 95 % o más en productos de S/ 1 a S/ 5 (por ejemplo un marco LED a S/ 1 "antes S/ 71"). Conviene exigir un precio mínimo, por ejemplo S/ 10, y revisar con lupa lo que pase del 95 %.
  - Confirmar `AvailableQuantity > 0`.
  - Plaza Vea, Oechsle y Promart comparten marketplace, así que el mismo producto aparece en las tres. Hay que deduplicar por nombre y precio.

---

## Grupo 2 · Viajes, vuelos y hoteles (`viajes`)

| Sitio | Vía | Permiso | Estado |
|---|---|---|---|
| Travelpayouts (datos de Aviasales) | API oficial | Programa de afiliados: registro gratuito y solicitud de acceso | Endpoints verificados en su documentación |
| JetSMART | HTML y JSON de la portada `/pe/es/` | robots.txt comprobado | Activo: 12 tarifas desde Lima en la muestra; con tasas |
| LATAM | Navegador oculto | Permite el sitio general; bloquea compra, asientos y login. Publica un `llms.txt` (índice para agentes de IA) | Falta programar |
| SKY | HTML y JSON integrado en página de ofertas | /robots.txt devuelve portada HTML, sin directivas publicadas | Activo: tarifas publicadas desde Lima; precio base + tasas |
| Despegar | HTML | Solo sus páginas de ofertas (`/vuelos-baratos`, `/paquetes/`, `/hoteles/h-*/`); bloquea buscador y APIs | Parcial |
| Civitatis, GetYourGuide, Viator | HTML | Páginas de tours permitidas; bloquean carrito y checkout | Falta programar |
| Booking.com | — | No deja leer ni su `robots.txt` | No usar |
| Diners Club Perú | HTML | El listado público utilizado por este proyecto responde | Activo; leer revisión anterior |

### API de Travelpayouts (verificado en su documentación)

```
https://api.travelpayouts.com/v1/prices/cheap?origin=LIM&destination=MIA&currency=usd
https://api.travelpayouts.com/v1/prices/calendar?origin=LIM&destination=MIA&depart_date=2026-12&calendar_type=departure_date
https://api.travelpayouts.com/v2/prices/special-offers        # responde XML
```

- El token va en la cabecera `X-Access-Token` (o como parámetro `token`). Se guarda como secreto, igual que `NTFY_TOPIC`.
- Los datos salen de la caché de búsquedas de Aviasales, no son tarifas en vivo: sirven para detectar que algo bajó, no para reservar a ese precio.
- Tiene límites de consultas por segundo, así que conviene vigilar pocas rutas y espaciar.

### Diferencia importante de este grupo

En viajes casi nunca hay un "% de descuento" publicado. Lo útil es el **precio mínimo histórico**: el monitor guarda el precio de cada ruta, hotel o tour que te interese y avisa cuando baja respecto de lo visto antes (con un umbral de al menos 50 % y una referencia histórica comparable y verificable). Por eso este grupo necesita una memoria de precios, además de la memoria de avisos que ya existe.

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

## Frecuencias sugeridas

| Grupo | Cada cuánto | Por qué |
|---|---|---|
| `comida` | 30 minutos | Las ofertas relámpago duran poco |
| `retail` | 3 horas | Los precios cambian por día, no por minuto |
| `viajes` | 6 horas | Cuidar la cuota de la API y no saturar |

## Implementación de vuelos · 17 de septiembre de 2026

`monitor/flights.py` lee JetSMART en https://www.jetsmart.com/pe/es/ (`let list = JSON.parse(...)`, sin ejecutar JS) y SKY en https://www.skyairline.com/flights/es-pe/ofertas-descuentos (`__NEXT_DATA__`, Apollo StandardFareModule.fares). La página `/pe/es/minisitios/promo` de JetSMART respondió pero no incluía tarifas, por eso no se usa.

Se leyeron robots.txt y cuerpos completos públicos de ambas fuentes. JetSMART publica reglas que no excluyen la portada. SKY devuelve su portada HTML en /robots.txt, sin directivas: no se presenta esto como permiso explícito; se continúa solo con su página pública de ofertas. Si aparecen directivas, se respetan; una respuesta desconocida o un bloqueo detiene la fuente. Cada ronda usa dos lecturas por aerolínea separadas por 1,5 segundos. No sigue enlaces al motor de reservas. JetSMART: `pi.pen` con tasas, comprobado contra `p.pen + i.pen`, salida `dep=LIM`, fecha/hora `date`, número `fn`, clase `c`, plazas `s>0`. SKY: `totalPrice` en su moneda, con el aviso público `+ tasas`, `originAirportCode=LIM`, solo ida y fecha futura; ignora precios vistos hace más de 24 horas. No se interpreta `totalPrice` como total final con impuestos.

El usuario autorizó caídas >=50 % con historial comparable. Se compara contra el mínimo de los 30 días anteriores con al menos tres días distintos de observaciones, excluyendo el día actual (UTC). No se inventa historial inicial. La memoria viaja en state/viajes.json y los avisos al tema existente de viajes. SKY permite comparar mínimos publicados por fecha, no garantiza mismo vuelo ni equipaje. Los formatos cambiados generan error visible; cero alertas con historial insuficiente es normal.

## Conveniencia y supermercados · revisión del 17/18 de septiembre de 2026

- **Tambo activo:** https://www.tambo.pe/pedir, datos JSON públicos en window.__remixContext, menuData.products. 79 productos en la muestra. availabilityAt.finalPrice/basePrice, available y visible. Precios por pack/presentación, cobertura por confirmar; no se ingresa dirección ni sesión.
- **Makro activo:** catálogo VTEX de https://makro.plazavea.com.pe (enlazado por Makro). La consulta pidió hasta 50 productos ordenados por descuento y devolvió solo 10; cobertura parcial, no inventario completo. Stock positivo y comparación Price/ListPrice. Respeta presentaciones mayoristas y pide confirmar mínimos y disponibilidad en Lima. Excluye electrodomésticos, tecnología y muebles de este tema.
- Ambos verifican robots.txt en cada ronda, calculan >=60 % sin redondear al alza y descartan referencias extremas >=95 %. No se exige S/10 mínimo a alimentos. Ninguna oferta alcanzó 60 % en la muestra de evaluación. Se ejecutan en catalogos.yml cada 30 minutos y usan NTFY_TOPIC (grupo original de comida/bazar), con memoria independiente state/comida.json y deduplicación de siete días. No deduplica una misma promoción entre Rappi y la tienda directa, porque son canales/condiciones distintos.
- **Mass pendiente:** https://catalogos.tiendasmass.com.pe respondió, pero solo expuso estructura de página, sin catálogo verificable de precios anteriores/actuales. robots.txt respondió 404. No se activa una fuente que siempre devuelva cero sin leer productos.
- **Listo pendiente:** https://www.primax.com/nosotros/tiendas/ enlaza un encarte PDF de septiembre/octubre de 2026. No se ha validado un lector por producto, vigencia y precio anterior. No está activo; tampoco se tratan sorteos, puntos o sellos como descuentos.
- **Formato ntfy móvil:** producto, precio/descuento y referencia en líneas separadas; bloques separados por espacio (y separador en los lotes). No se insertan marcas Markdown que la app pueda mostrar literalmente. La documentación de ntfy limita el renderizado Markdown a la web: https://docs.ntfy.sh/publish/#markdown-formatting.
