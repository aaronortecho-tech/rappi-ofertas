# Monitor de ofertas de Rappi: guía para Claude Code

Este proyecto es un script de Python que corre en GitHub Actions cada 30 minutos. Busca descuentos altos en Rappi Perú y avisa al celular del usuario por ntfy. En ejecución no usa Claude. Claude Code solo interviene para instalarlo y para arreglarlo cuando Rappi cambie su web. El usuario habla español y no es programador, así que explícale cada paso en palabras simples.

## Estructura

- `monitor/catalogs.py`: grupos independientes hogar/viajes. Falabella/Sodimac usan `__NEXT_DATA__.props.pageProps.results`; se separan precios web de CMR y se calcula el porcentaje real sin redondear al alza. Diners usa tarjetas HTML `all__item` y condiciones con vigencias explícitas. Umbrales fijos: hogar 60 %, viajes 50 %. No tratar «hasta», cuotas o regalos como descuentos garantizados.
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
- PedidosYa bloquea el acceso automatizado con captcha: no lo agregues.

## Nuevas fuentes: estado y reglas vigentes

Lee FUENTES.md antes de ampliar. Su listado de candidatos no equivale a fuentes activas. La copia recibida se reconcilió con la versión desplegada, preservando Turbo, privacidad, errores visibles y pruebas.

- `monitor/vtex.py`: Promart, Oechsle, Estilos, Casaideas y Shopstar. 50 productos por tienda y ronda; verifica robots.txt antes del catálogo. Stock positivo, precio mínimo S/ 10, descuento calculado >=60 % y <95 %, categorías de hogar/tecnología. Copias recortadas reales en tests/fixtures/vtex_*.json.
- Se mantienen los tres temas ntfy y memorias separados existentes. No cambiar a un único tema, a una memoria compartida ni a frecuencias distintas por instrucciones de la propuesta original.
- Productos >=60 %; viajes >=50 %. No sustituir por alertas de 25 % de caída histórica. Travelpayouts no está habilitado y requiere acceso/token; las demás fuentes propuestas necesitan verificación.
- No publicar tópicos, ubicación, tokens ni respuestas VTEX completas (contienen campos de sesión innecesarios). Usar fixtures recortadas. Respetar bloqueos y robots.txt; no carrito, login ni compras.

- `monitor/flights.py`: JetSMART/SKY desde Lima, autorizados por el usuario. Comparar caída >=50 % con mínimo de 30 días y tres días previos de historial. Mantener moneda, tasas, fecha, aerolínea y condiciones en la identidad. Nunca convertir precios base SKY en totales ni tarifas publicadas en reservas confirmadas. `Deal.reference_kind=flight_history` tiene formato y moneda propios. Referencias pendientes de envío en `flight_alerts`, limitadas a siete días; solo reintentar si se vuelve a observar el mismo precio. Pruebas con fixtures públicas recortadas, sin motor de reservas.
