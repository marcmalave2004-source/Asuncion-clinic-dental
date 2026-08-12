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

### ⚠️ Antes de nada: la autenticación no está verificada

No pude acceder a `docs.trading212.com` desde el entorno donde escribí este
código (la red del sandbox lo bloqueaba), así que el formato exacto de la
cabecera de autenticación en `t212_client.py` viene de fuentes de terceros
que **se contradecían entre sí** (una API key sola vs. un par API
key+secret con HTTP Basic Auth). Por defecto, el cliente usa Basic Auth si
configuras un secret, y si no, manda la key sin más en `Authorization`.

**Antes de confiar en esto con dinero real:**

1. Genera una API key en la app de Trading 212 (cuenta Invest o ISA →
   Ajustes → API) y fíjate si te da una sola clave o un par clave+secreto.
2. Pon lo que te haya dado en `.env` (`TRADING212_API_KEY` /
   `TRADING212_API_SECRET`).
3. Corre el chequeo de solo lectura (no coloca ninguna orden):
   ```bash
   python -m trading_bot.main check-broker
   ```
4. Si falla con 401, entra a `docs.trading212.com/api` tú mismo y ajusta
   `_auth_header()` en `trading_bot/t212_client.py` según el formato real.

También verifica el formato exacto del ticker de tu instrumento (usé
`AAPL_US_EQ` como ejemplo — confírmalo contra el endpoint de instrumentos o
la documentación) antes de intentar colocar una orden real.

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
