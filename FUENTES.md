# Fuentes de ofertas en Perú

Guía de los sitios que se pueden vigilar, ordenados en tres grupos. La lista original recibida es una propuesta de investigación; sus afirmaciones no equivalen a integración ni a cobertura comprobada. La revisión de implementación siguiente indica qué se comprobó realmente.


## Revisión e integración · 17 de septiembre de 2026

- **Activos:** Rappi/Turbo (comida, 60 %); Falabella/Sodimac y ahora Promart, Oechsle, Estilos, Casaideas y Shopstar (hogar, 60 %); beneficios Diners (viajes, 50 %). Se conservan los tres temas separados y los horarios existentes de 30 minutos. Las frecuencias de la tabla final son propuestas, no configuración aplicada.
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
| JetSmart | Navegador oculto | Permite todo menos el motor de reservas | Falta programar |
| LATAM | Navegador oculto | Permite el sitio general; bloquea compra, asientos y login. Publica un `llms.txt` (índice para agentes de IA) | Falta programar |
| SKY | Navegador oculto | No publica `robots.txt`; su web es puro JavaScript | Falta programar |
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
