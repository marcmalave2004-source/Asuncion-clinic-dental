# trading_bot

Bot de trading algorítmico en Python, listo para operar en real, construido con
capas de seguridad explícitas porque puede perder dinero real si se configura
mal o si el mercado se mueve en contra.

**Estrategia por defecto:** cruce de EMA (12/26) con filtro RSI, solo posiciones
largas (sin shorts, sin apalancamiento), stop-loss/take-profit basados en ATR.
Es un punto de partida razonable y bien entendido — no es una garantía de
rentabilidad. Rentabilidad pasada de cualquier indicador no predice resultados
futuros. **Esto no es asesoría financiera.**

## Arquitectura

```
trading_bot/
  config.py      configuración (config/config.yaml + variables de entorno)
  exchange.py    wrapper sobre ccxt (crypto - ~100 exchanges)
  t212_client.py cliente REST de Trading 212 (acciones/ETFs) - ver aviso de auth abajo
  market_data.py datos OHLCV: ccxt para crypto, Yahoo Finance para Trading 212
  broker.py      abstracción de cuenta/órdenes sobre ccxt o Trading 212
  indicators.py  EMA, RSI, ATR
  strategy.py    lógica de señales (compra/venta/mantener)
  risk.py        tamaño de posición por % de riesgo, stop/target, kill switch diario
  portfolio.py   estado de la posición abierta, persistido en disco
  session.py     cierre forzado antes del cierre de mercado (day trading)
  executor.py    único módulo que puede colocar una orden real; aplica los gates de seguridad
  storage.py     registro de operaciones y equity en SQLite (auditoría)
  backtester.py  simulación contra datos históricos
  runner.py      loop de trading en vivo/paper
  main.py        CLI (backtest / run --mode paper|live / check-broker)
```

Dos "brokers" soportados, seleccionados con `exchange.provider` en `config.yaml`:

| | `provider: ccxt` | `provider: trading212` |
|---|---|---|
| Mercado | Cripto (spot) | Acciones y ETFs |
| Exchange/broker | ~100 vía ccxt (Binance por defecto) | Trading 212 (cuenta Invest o Stocks ISA) |
| Datos de precio (velas) | El propio exchange | Yahoo Finance (T212 no expone histórico) |
| Testnet/paper propio del broker | Sí (sandbox de ccxt, según exchange) | Sí (entorno demo de T212) |

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # incluye pytest

cp config/config.example.yaml config/config.yaml
cp .env.example .env
# Edita .env con tus claves de API (nunca lo subas a git)
```

## Ejecutar los tests

```bash
PYTHONPATH=. pytest -q
```

## 1. Backtest (sin claves de API, sin riesgo)

Usa datos públicos históricos del exchange para validar la estrategia antes de
arriesgar nada:

```bash
python -m trading_bot.main backtest --since 2023-01-01 --until 2024-01-01 --balance 1000
```

Imprime número de operaciones, win rate, retorno total, drawdown máximo y
profit factor. **Ajusta `config/config.yaml` y vuelve a correr el backtest
hasta que el comportamiento te convenza antes de pasar a paper o live.**

## 2. Paper trading (simulado, con precios en vivo)

```bash
python -m trading_bot.main run --mode paper
```

Corre contra el mercado en tiempo real pero nunca coloca órdenes reales; todo
se registra en `state/trades.db` como si fueran operaciones reales, con un
balance simulado. Es el paso obligatorio antes de vivo.

## 3. Trading en vivo (dinero real)

**Esto puede perder dinero real.** El bot exige tres confirmaciones
independientes antes de colocar una sola orden real — si falta cualquiera de
ellas, se niega a arrancar:

1. `config/config.yaml`: `runtime.dry_run: false`
2. Variable de entorno `LIVE_TRADING=true`
3. Variable de entorno `LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK`

```bash
export LIVE_TRADING=true
export LIVE_TRADING_CONFIRM=I_ACCEPT_THE_RISK
python -m trading_bot.main run --mode live
```

Además pedirá una confirmación interactiva (`y/N`) antes de arrancar.

### Recomendaciones antes de ir a real

- Empieza con `exchange.use_testnet: true` (testnet de Binance) para probar
  la integración con órdenes reales sin dinero real.
- Cuando pases a mainnet, usa una cuenta de API con **solo permisos de
  trading spot**, nunca de retiro (withdrawal). Así, aunque las claves se
  filtren, nadie puede sacar tus fondos.
- Empieza con `risk.risk_per_trade_pct` bajo (1% o menos) y un
  `risk.max_daily_loss_pct` conservador.
- Vigila los logs en `logs/trading_bot.log`.

### Kill switch / parada de emergencia

En cualquier momento, crea un archivo llamado `STOP` en el directorio del
proyecto (`touch STOP`) y el bot se detiene antes de colocar cualquier orden,
en el siguiente ciclo. Bórralo para reanudar.

El bot también trae un **kill switch automático de pérdida diaria**: si el
equity cae más del `risk.max_daily_loss_pct` configurado respecto al balance
al inicio del día (UTC), deja de abrir posiciones nuevas hasta el día
siguiente (las posiciones abiertas se siguen gestionando con su stop-loss).

## Trading 212 (acciones/ETFs)

```bash
cp config/config.trading212.example.yaml config/config.yaml
```

### Autenticación (confirmada contra la documentación oficial)

- **Auth:** HTTP Basic, con tu **API Key** como usuario y tu **API Secret**
  como contraseña (`Authorization: Basic base64(key:secret)`). Si tu key no
  viene con secreto, el cliente usa el esquema legacy y manda la key sola en
  `Authorization`. Ya está implementado así por defecto en `t212_client.py`.
- **Entornos:** `https://demo.trading212.com/api/v0` (paper) y
  `https://live.trading212.com/api/v0` (real).
- **Solo funciona con cuentas Invest y Stocks ISA**, y las órdenes solo se
  ejecutan en la **moneda principal de la cuenta** (cuentas multi-divisa no
  están soportadas por la API).
- El campo de "cash disponible" dentro de `/equity/account/summary` está
  confirmado contra una respuesta real: `cash.availableToTrade` (junto a
  `reservedForOrders` e `inPies`). Ejemplo real de respuesta:
  ```json
  {"id": 50044619, "currency": "EUR", "totalValue": 4.49,
   "cash": {"availableToTrade": 4.49, "reservedForOrders": 0, "inPies": 0},
   "investments": {"currentValue": 0, "totalCost": 0, "realizedProfitLoss": 0, "unrealizedProfitLoss": 0}}
  ```
  `broker.py` lee `cash.availableToTrade` con un par de nombres alternativos
  como respaldo por si tu respuesta viene con forma distinta.

Verifica la conexión y tu balance con (solo lee, no coloca ninguna orden —
seguro de correr incluso con una API key de la cuenta real):

```bash
python -m trading_bot.main check-broker
```

También confirma el ticker exacto de tu instrumento contra
`GET /equity/metadata/instruments` — usé `AAPL_US_EQ` como ejemplo en el
config, que sigue el patrón `SYMBOL_MERCADO_EQ`.

**Recomendación de seguridad adicional:** Trading 212 permite restringir tu
API key a un conjunto de IPs concretas desde los ajustes de tu cuenta — hazlo
si vas a correr el bot desde un servidor con IP fija.

### Limitaciones de la API pública de Trading 212

- **Solo cuentas Invest y Stocks ISA.** Las cuentas CFD (apalancamiento,
  posiciones cortas) y SIPP no están soportadas por la API pública — el bot
  no puede operar ahí.
- **Sin datos históricos de velas.** Por eso `market_data.py` usa Yahoo
  Finance (gratis, sin API key) para calcular EMA/RSI/ATR, y la API de T212
  se usa solo para consultar balance y colocar/cancelar órdenes.
- **Solo long, sin apalancamiento**, igual que en el lado cripto — compras y
  vendes acciones/ETFs, nunca en corto.
- Yahoo Finance limita cuánto histórico intradía puedes pedir (ej. ~60 días
  para velas de 5-30 min). Por eso el config de ejemplo usa velas diarias
  (`timeframe: 1d`), que además encaja mejor con T212 (pensado para
  invertir, no para alta frecuencia).

### Paper trading con Trading 212

Tienes dos formas de probar sin arriesgar dinero real:

1. **Modo `dry_run` del propio bot** (`runtime.dry_run: true`, por defecto):
   no llama a la API de T212 en absoluto, todo se simula localmente con un
   balance ficticio.
2. **Entorno demo de Trading 212** (`exchange.t212_environment: demo`): si
   pones `dry_run: false`, el bot llama de verdad a la API pero contra el
   entorno demo de T212 (dinero simulado, gestionado por ellos). Sigue
   necesitando pasar los gates de `LIVE_TRADING`/`LIVE_TRADING_CONFIRM`
   descritos arriba, aunque no haya dinero real en juego — es una
   simplificación deliberada para no tener dos caminos de código distintos
   para "llamar a la API de verdad".

### Day trading y cierre forzado antes del cierre de mercado

Por defecto el bot mantiene posiciones abiertas durante días (swing
trading). Para day trading real (abrir y cerrar operaciones dentro del
mismo día):

1. Pon `exchange.timeframe` en algo intradía, ej. `15m`.
2. Baja `runtime.poll_interval_seconds` (ej. `300`, cada 5 min) para
   reaccionar más rápido que con velas diarias.
3. Activa el bloque `session` para forzar el cierre de cualquier posición
   abierta antes de que cierre el mercado, en vez de dejarla de un día para
   otro — un stop-loss no protege frente a un gap de apertura (el precio
   puede saltar mucho más allá de tu stop mientras el mercado está cerrado):
   ```yaml
   session:
     enabled: true
     timezone: America/New_York   # zona horaria del mercado del ticker
     close_time: "16:00"           # hora de cierre
     close_buffer_minutes: 15      # cierra 15 min antes, para dar tiempo a que la orden se ejecute
   ```

`session.enabled: false` (por defecto) no afecta en nada al modo swing ni a
cripto (mercados 24/7, sin "cierre" que forzar). No tiene en cuenta días
festivos del mercado — como mucho, una posición se queda abierta un día
extra en un festivo, no es motivo de fallo.

### Varios instrumentos a la vez

Por defecto el bot opera un solo símbolo (`exchange.symbol` /
`exchange.t212_ticker`). Para vigilar y operar **varias acciones/ETFs en
paralelo**, sustitúyelo por una lista `exchange.instruments`:

```yaml
exchange:
  provider: trading212
  timeframe: 15m
  t212_environment: live
  # instruments reemplaza a symbol/t212_ticker/data_symbol cuando está presente
  instruments:
    - symbol: AAPL              # ticker de Yahoo Finance, usado también como nombre interno
      t212_ticker: AAPL_US_EQ    # código de instrumento de Trading 212
    - symbol: VOO
      t212_ticker: VOO_US_EQ
    - symbol: MSFT
      t212_ticker: MSFT_US_EQ
      data_symbol: MSFT           # opcional: solo si el ticker de Yahoo difiere del symbol
```

Cada ciclo, el bot revisa la señal de **todos** los instrumentos de la
lista. Cuántas posiciones puede tener abiertas **a la vez, en total**, lo
controla `risk.max_open_positions` (antes existía en el config pero no se
aplicaba de verdad — ahora sí se respeta). Si varias señales de compra
saltan en el mismo ciclo, el balance disponible se va descontando entre
ellas para no sobre-dimensionar las posiciones.

El backtest sigue probando **un instrumento a la vez** — usa `--symbol` para
elegir cuál de la lista:
```bash
python -m trading_bot.main backtest --since 2026-06-01 --until 2026-08-14 --symbol VOO
```

**Recuerda las limitaciones reales de Trading 212** (ya comentadas más
abajo): esto amplía a más acciones/ETFs dentro de tu cuenta Invest/ISA, pero
no habilita índices ni opciones — esos no están disponibles en la API de
T212 sea cual sea la configuración.

## Ejecutarlo 24/7 sin ordenador propio (GitHub Actions)

En vez de dejar el bot corriendo en un bucle infinito en tu máquina/Codespace
(que se para si cierras la sesión), `run --mode ... --iterations N` permite
correr un número fijo de ciclos y salir — el workflow
`.github/workflows/trading-bot.yml` usa esto para ejecutar **una sola
iteración cada ~5 minutos** vía GitHub Actions, gratis, sin necesitar
ningún servidor propio ni tarjeta de crédito.

Como cada ejecución de Actions es una máquina nueva sin disco persistente,
el estado del bot (posición abierta, registro de operaciones, kill switch
diario) se guarda en la carpeta `state/` y el propio workflow lo comitea de
vuelta al repositorio al final de cada ejecución, para que la siguiente
ejecución lo recupere.

### Configurar

1. En GitHub, ve a tu repositorio → **Settings** → **Secrets and variables**
   → **Actions** → **New repository secret**, y añade estos cuatro secretos
   (mismos nombres y valores que ya tienes en tu `.env` local):
   - `TRADING212_API_KEY`
   - `TRADING212_API_SECRET`
   - `LIVE_TRADING` → `true`
   - `LIVE_TRADING_CONFIRM` → `I_ACCEPT_THE_RISK`
2. Sube `config/config.yaml` con `runtime.dry_run: false` (ya debería estarlo
   si vienes de probarlo en real).
3. Ve a la pestaña **Actions** del repo. Si es la primera vez, puede pedirte
   habilitar Actions para el repositorio — confírmalo.
4. Busca el workflow **"Trading Bot"** en la lista de la izquierda y
   actívalo si aparece deshabilitado. A partir de ahí corre solo, cada ~5
   minutos, sin que tengas el navegador abierto.

### Parar el bot

La forma más simple y fiable: pestaña **Actions** → **Trading Bot** → menú
**"..."** → **Disable workflow**. Vuelve a activarlo cuando quieras
reanudar. El archivo `STOP` en la raíz del repo también funciona, pero solo
hace efecto en la siguiente ejecución programada.

### Limitaciones de este modo

- El cron de GitHub Actions es "mejor esfuerzo": bajo mucha carga en la
  plataforma puede retrasarse bastante más de 5 minutos. No es un
  reloj exacto.
- Cada ejecución hace un `git commit` + `git push` del estado — verás ese
  historial de commits automáticos en el repo, es esperado.
- Si corres el bot en paralelo desde tu Codespace/local **y** desde este
  workflow al mismo tiempo, pueden pisarse el estado entre sí. Usa un solo
  método a la vez.

## Seguridad de credenciales

- Las claves de API se leen únicamente de variables de entorno (`.env`,
  ignorado por git). Nunca se escriben en `config.yaml` ni en el código.
- `executor.py` es el único punto del código que puede llamar a
  `create_market_order`; todo pasa por sus comprobaciones de `dry_run` y
  autorización de trading en vivo.

## Extender el bot

- Nuevo exchange: cambia `exchange.id` en `config.yaml` a cualquier id
  soportado por [ccxt](https://github.com/ccxt/ccxt) (Binance, Kraken,
  Coinbase, Bybit, etc.).
- Nueva estrategia: implementa tu lógica en `strategy.py` siguiendo la firma
  de `signal_for_row`; `backtester.py` y `runner.py` no necesitan cambios.
