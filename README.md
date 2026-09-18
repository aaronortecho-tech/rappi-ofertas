# Monitor de ofertas de Rappi

## Grupos de avisos

El proyecto mantiene tres temas independientes de ntfy. Los nombres reales de los temas se guardan exclusivamente como secretos de GitHub.

| Grupo | Fuentes activas | Mínimo | Secreto |
|---|---|---|---|
| Ofertas del día | Rappi, Rappi Market/Turbo, Tambo y Makro | 60 % | `NTFY_TOPIC` |
| Hogar y tecnología | Falabella, Sodimac, Promart, Oechsle, Estilos, Casaideas y Shopstar, con vendedores terceros | 60 % | `NTFY_TOPIC_HOGAR` |
| Viajes y escapadas | Diners Club y tarifas publicadas de JetSMART/SKY desde Lima | 50 % | `NTFY_TOPIC_VIAJES` |

**Estado de cobertura:** Ripley, LATAM y Despegar no están activados: las comprobaciones de acceso devolvieron bloqueos. PedidosYa tampoco está integrado. Un resultado exitoso de los grupos nuevos solo confirma las fuentes activas de la tabla.

El workflow **Ofertas de hogar y viajes** corre cada 30 minutos y admite una prueba manual que envía un mensaje a cada tema nuevo. Usa memorias separadas (`state/hogar.json` y `state/viajes.json`) y comparte la exclusión de ejecución con Rappi para evitar conflictos al guardar los archivos. Solo se marcan como avisadas las ofertas cuyo envío fue aceptado por ntfy.

### Hogar y tecnología

- Las cinco tiendas VTEX nuevas aportan una muestra de 50 productos por tienda, ordenada por descuento. Se revisa robots.txt en cada ronda y se exige stock, precio mínimo de S/ 10 y descuento entre 60 % y menos de 95 %. Se filtran categorías de hogar, muebles, tecnología y electrodomésticos. Las ofertas extremas se omiten hasta poder verificarlas.
- Ver [FUENTES.md](FUENTES.md) para distinguir fuentes activas, propuestas y bloqueadas. La cobertura nueva comparte el límite de avisos del grupo hogar.

- Revisa tecnología, muebles, electrodomésticos y decoración de Falabella/Sodimac. Por categoría consulta la primera página de resultados filtrados por 60 % y otra página que va rotando. Es una selección periódica, no una lectura completa del inventario en cada ronda.
- Calcula el descuento con los precios de la ficha, sin redondear hacia arriba. Incluye vendedores terceros y muestra quién vende. Si el mínimo solo se alcanza con CMR, lo indica expresamente. Si también califica el precio web, prioriza esa opción.
- La referencia tachada del vendedor no se presenta como precio histórico. Desde la activación guarda mínimos observados durante hasta 30 días y los muestra cuando ya existe historial. No asegura que el descuento anunciado equivalga a una rebaja frente al precio habitual.
- Máximo 8 mensajes de hasta 3 productos por ronda; no marca como enviadas las ofertas que quedaron fuera del límite. No repite una misma ficha/precio/condición durante 7 días. Un cambio de precio puede generar un aviso nuevo.
- Evita repetir el mismo SKU, vendedor y oferta entre Falabella y Sodimac, y alterna categorías para que decoración no desplace todos los avisos de muebles o tecnología. El historial se limita a 12 000 combinaciones recientes de producto/vendedor/condición.
- Stock, envío y disponibilidad en tu dirección se confirman en la tienda. Las páginas se consultan sin cuenta personal.

### Viajes y escapadas

- **Vuelos desde Lima:** JetSMART (portada pública, con tasas) y SKY (página pública de ofertas, precio base + tasas). Solo fechas futuras y solo ida. Se revisa robots.txt antes de cada lectura; sin consultar buscadores de reservas, iniciar sesión ni comprar.
- **Historial:** avisa por una caída calculada de al menos 50 % frente al mínimo observado en los 30 días anteriores, con al menos tres días previos distintos. La primera lectura solo registra precios. Compara aerolínea, ruta, fecha, moneda y condiciones publicadas; JetSMART además conserva vuelo/hora/clase. SKY publica mínimos por fecha sin vuelo confirmado ni equipaje: el aviso expresa esa limitación. No es un descuento anunciado ni una tarifa final garantizada.
- Los cambios de fecha, vuelo/clase de JetSMART o condiciones identificables crean una comparación nueva. No compara vuelos de distintas fechas ni monedas. Mantiene la referencia de una caída hasta siete días para reintentar entregas fallidas, siempre que el mismo precio vuelva a observarse; evita repetir avisos ya entregados.
- Cobertura parcial: solo las tarifas destacadas que estas páginas muestran, no todas las combinaciones de destino y fecha. No consulta LATAM, Despegar ni Travelpayouts. No requiere un secreto nuevo.

- Revisa el listado público de viajes de Diners: descuentos, hoteles y campañas de viajes nacionales/internacionales. Verifica las condiciones y las fechas de compra de las promociones candidatas antes de avisar.
- Exige un descuento explícito de al menos 50 %. Excluye anuncios que solo dicen «hasta», cuotas sin intereses, regalos, campañas vencidas y campañas sin vigencia interpretable. Por eso es normal que no haya avisos aun cuando la página muestre beneficios.
- Los avisos de Diners son **beneficios generales de Diners**, no cotizaciones de vuelos, hoteles o tours para fechas concretas. En vuelos se toma Lima como salida: se descartan otras salidas explícitas, y si la campaña es general el mensaje pide confirmar que incluya Lima.
- No consulta tarifas en vivo de LATAM/Despegar, no reserva ni compra. Los avisos conservan condiciones y un enlace oficial. Las promociones con fechas o formatos que el lector no reconoce se omiten de forma conservadora.

Pruebas locales de los nuevos grupos, sin enviar ni guardar memoria:

```powershell
python -m monitor.catalogs --grupo hogar --sin-enviar --prueba
python -m monitor.catalogs --grupo viajes --sin-enviar --prueba
```

---

Te avisa en el celular cuando hay descuentos de **60 % o más** en Rappi Perú: restaurantes, supermercados, farmacias, licorerías y tiendas. Funciona solo en GitHub cada 30 minutos, **sin usar Claude ni gastar tokens**.

## Qué revisa

| Sección | Cómo | Frecuencia |
|---|---|---|
| Restaurantes | Un navegador oculto abre rappi.com.pe con tu ubicación, activa el filtro **Promos** y revisa el menú de los locales que anuncian tu descuento mínimo. | Cada ronda |
| Tiendas | Lee la página de **Ofertas** de las tiendas del catálogo público (supermercados, farmacias, licorerías, express y Rappi Mall). | 40 tiendas por ronda; la vuelta completa depende del tamaño del catálogo |
| Cadenas (respaldo) | Si falla la lista de restaurantes, revisa Fridays, Chili's, Bembos, Chinawok, KFC, Popeyes, Papa John's, McDonald's y Little Caesars. | Solo cuando hace falta |

**Rappi Market / Turbo:** además de las tiendas encontradas en las categorías generales, se incorporan los locales del directorio público de Turbo en Lima. Cuando toca revisar uno de estos locales, se leen sus ofertas y los pasillos **Hogar y bazar** o **Hogar y vehículos** enlazados en su página. Los productos de esos pasillos usan el mismo mínimo de descuento y la misma memoria para evitar avisos repetidos. Estos locales forman parte del grupo rotativo de 40 tiendas; no se revisan todos cada 30 minutos.

Cómo son los avisos:

- Llega una notificación por local con sus mejores ofertas. Al tocarla se abre el local en Rappi.
- Los descuentos de **80 % o más** llegan con prioridad máxima: vibración larga y aviso en pantalla.
- No repite la misma oferta durante 7 días. Si aparece una oferta nueva en el mismo local, sí avisa.
- Si en una ronda hay más de 8 locales, los demás llegan juntos en un resumen.
- Si Rappi cambia su web y el monitor falla 3 rondas seguidas, te avisa como máximo una vez al día.

## Instalación (una sola vez, unos 15 minutos)

### 1. Instala ntfy en tu celular

1. Instala **ntfy** desde Play Store o App Store. Es gratis y no pide cuenta.
2. Inventa un nombre de tema difícil de adivinar, por ejemplo `tu-tema-con-un-sufijo-aleatorio`. Cualquiera que conozca el nombre puede ver tus avisos, así que no uses algo obvio.
3. En la app toca **+**, escribe ese nombre y suscríbete.

### 2. Copia tu ubicación

En Google Maps, mantén presionado el punto donde recibes tus pedidos y copia los números que aparecen, por ejemplo `-12.0977, -77.0365`.

### 3. Sube el proyecto a GitHub

**Opción A: con Claude Code (recomendada).** Abre esta carpeta en Claude Code y pega:

> Lee CLAUDE.md y ayúdame a instalar este monitor: crea un repositorio público llamado rappi-ofertas en mi GitHub, súbelo, configura los secretos NTFY_TOPIC y RAPPI_UBICACION (pregúntame los valores) y lanza una ejecución de prueba.

**Opción B: a mano.**

1. Crea un repositorio **público** en <https://github.com/new>, por ejemplo `rappi-ofertas`.
2. Toca **uploading an existing file** y arrastra todo el contenido de esta carpeta, incluida la carpeta `.github`. Luego toca **Commit changes**.
3. Entra a **Settings → Secrets and variables → Actions → New repository secret** y crea estos dos secretos:
   - `NTFY_TOPIC`: el nombre de tu tema de ntfy.
   - `RAPPI_UBICACION`: tus coordenadas, por ejemplo `-12.0977, -77.0365`.
4. Ve a **Actions → Monitor de ofertas Rappi → Run workflow** y deja marcada la prueba. En unos minutos te llegarán **✅ Monitor de ofertas activado** y **🧪 Prueba del monitor de Rappi**.

Desde ese momento el monitor corre solo cada 30 minutos.

### ¿Por qué un repositorio público?

- En repositorios públicos, GitHub Actions es gratis y sin límite de minutos. En privados solo hay 2 000 minutos gratis al mes, y este monitor usaría más. Si prefieres uno privado, cambia en `.github/workflows/monitor.yml` el `cron` a `"7 */2 * * *"` (cada 2 horas) y `MINUTOS_ENTRE_RONDAS` a `"120"`.
- Tus datos no quedan a la vista. El tema y la ubicación se guardan como secretos, que GitHub oculta en los registros. La memoria del monitor (`state/state.json`) no guarda tu ubicación, y las ofertas que ya te avisó quedan como hashes SHA-256. Los hashes no son cifrado y no garantizan anonimato frente a quien ya conozca las ofertas.
- En repositorios públicos, GitHub pausa las tareas programadas si pasan 60 días sin actividad en el repositorio. El monitor guarda su memoria cada vez que envía avisos, así que normalmente habrá movimiento. Si aun así se pausa, GitHub te avisa por correo y lo reactivas en **Actions → Enable workflow**.

## Ajustes opcionales

Se crean en **Settings → Secrets and variables → Actions → Variables**. Los que no crees usan el valor por defecto.

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `DESCUENTO_MINIMO` | `60` | Descuento mínimo para avisarte. |
| `ALARMA_DESDE` | `80` | Desde este descuento el aviso llega como alarma. |
| `HORAS_SILENCIO` | (vacío) | Por ejemplo `23-7`: en ese horario (hora de Lima) los avisos llegan sin sonido. |
| `RAPPI_PRO` | `no` | Pon `si` si tienes Rappi Pro para incluir sus descuentos exclusivos. |
| `DISTANCIA_MAXIMA_KM` | (vacío) | Ignora restaurantes más lejanos que esta distancia. |
| `REPETIR_AVISO_HORAS` | `168` | Cada cuánto puede repetirse el aviso de la misma oferta. |
| `MAX_AVISOS_POR_RONDA` | `8` | Avisos individuales por ronda; el resto llega en un resumen. |
| `TIPOS_TIENDA` | `market, farmacia, express-big, licores, rappimall-parent` | Tipos de tienda que se revisan. |
| `TIENDAS_POR_RONDA` | `40` | Tiendas que se revisan en cada ronda. |
| `CADENAS` | Fridays, Chili's, Bembos… | Cadenas de respaldo, con el formato `6419-fridays`. |
| `REVISAR_TIENDAS` / `REVISAR_RESTAURANTES` | `si` | Permite apagar una sección. |
| `REVISAR_RAPPI_MARKET` | `si` | Amplía la lista con el directorio de Turbo y revisa los pasillos de hogar/bazar de Market/Turbo. Requiere `REVISAR_TIENDAS=si`. |
| `DETALLE_EN_LOGS` | `no` | Registros más detallados. En un repositorio público cualquiera podría ver los nombres de los locales. |

La ubicación va como **secreto**, no como variable.

## Cómo leer los avisos

- **🔥 -70% en Big Cheese Pizza**: lista los productos con su precio actual y el anterior.
- **🚨**: el descuento es de 80 % o más.
- **hasta -100% … no vi el producto en la web**: el local anuncia ese descuento, pero el producto no aparece en la web; suele estar solo en la app.
- **Descuento en toda la carta**: es un porcentaje sobre todo el pedido y normalmente pide un monto mínimo.
- **Cadena (revisa si aplica a tu zona)**: sale del respaldo por cadenas, que no sabe qué local te corresponde.

## Límites

- Rappi no tiene una API pública, así que el monitor lee su web. Si Rappi la cambia, puede dejar de funcionar. Cuando pase, te llegará un aviso ⚠️; abre la carpeta en Claude Code y pídele que lo revise.
- No detecta cupones, cashback ni promociones de bancos, porque no aparecen en los precios.
- Las tiendas se revisan para toda Lima, no para tu dirección. Confirma la cobertura en la app.
- Market/Turbo se revisa con los productos presentes en sus páginas públicas. No se garantiza todo el inventario, productos cargados solo al desplazarse o descuentos exclusivos de la app. Si el pasillo está vacío o no llega al descuento mínimo, no se envía aviso.
- PedidosYa no está incluido porque bloquea los accesos automatizados.
- Los términos de Rappi prohíben "acceder, utilizar y/o manipular los datos de Rappi". El monitor está hecho para uso personal: no inicia sesión, espacia sus consultas y no compra nada. Úsalo bajo tu responsabilidad.

## Probar en tu computadora (opcional)

```powershell
pip install -r requirements.txt
python -m playwright install chromium
$env:RAPPI_UBICACION = "-12.0977, -77.0365"
python -m monitor --sin-enviar --prueba
```

`--sin-enviar` muestra en pantalla los avisos que enviaría, sin mandarlos al celular.

Para las pruebas automáticas: `pip install -r requirements-dev.txt` y luego `python -m pytest -q`.

## Comprobación de la instalación

La prueba manual termina con error si falla alguna sección o si ntfy rechaza los avisos. Un aviso aceptado por ntfy no confirma que el celular lo haya mostrado: comprueba que llegue la notificación de prueba. Ante respuestas 403 o 429 de Rappi se detiene la ronda sin intentar el respaldo. Si no se puede guardar la memoria en GitHub, la ejecución también indica el error.

## Tambo y Makro y lectura en el celular

Tambo y Makro se revisan cada 30 minutos en el grupo original de comida/bazar (`NTFY_TOPIC`). Se leen sus catálogos públicos disponibles, no todo el stock por dirección; descuento mínimo 60 %, con disponibilidad y condiciones por confirmar al comprar. Los precios corresponden a la presentación o pack indicado. Memoria propia en `state/comida.json`; Mass y Listo siguen pendientes. Ver FUENTES.md.

Los avisos separan nombre, precio/descuento y precio anterior en líneas distintas, con espacio entre productos. Se prioriza texto legible en la app móvil: la negrita Markdown está documentada para la web, no se garantiza en el teléfono. No se cambian umbrales ni se reenvían ofertas antiguas solo por cambiar el formato.

Prueba manual de tiendas directas: `python -m monitor.catalogs --grupo comida --sin-enviar --prueba`. En GitHub Actions puede elegirse `grupo=comida` para probar solo ese tema.
