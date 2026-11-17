# Memetracker

Seguimiento de memecoins por token address. Pegas la dirección, la app detecta la cadena y, a partir de ahí, guarda cada 5 minutos precio, market cap, liquidez, volumen, compras/ventas, holders y seguridad. Con eso te enseña:

- **Mis coins**: todas las coins que sigues, con precio, cambio en 1h/24h, cuánto ha cambiado desde que la añadiste, market cap, liquidez, volumen, holders, tendencia, sentimiento, el movimiento en curso ("Subiendo +77% desde 15/11 12:00") y su último evento.
- **Historial de eventos** (hora de Madrid): cada subida o bajada de más del 20% con día y hora de inicio y fin, precio de origen y destino, y alertas en vivo (pump o dump de más del 25% en 1h, caída de liquidez, cambios de holders, nuevo máximo, aumento del riesgo). Si activas los avisos del navegador, te salta una notificación.
- **Ficha de cada coin**: velas de 15m, 1h y 1D con EMA9/21/50, volumen, RSI y flechas en cada subida o bajada; tendencia con señales (EMAs, RSI, MACD, Bollinger, volumen, soporte y resistencia); sentimiento por flujo de órdenes; narrativa (temática, descripción, redes, boosts); salud del token de 0 a 100; seguridad (RugCheck en Solana, GoPlus en EVM); gráficas históricas de holders, liquidez, market cap, volumen y presión compradora; notas y exportación a CSV.

## Cómo arrancarla (Windows)

1. Instala Python 3.10 o superior desde https://www.python.org/downloads/ y marca **"Add python.exe to PATH"**.
2. Haz doble clic en **`run.bat`**. Se abre una ventana negra y el navegador en http://localhost:8787
3. Deja esa ventana abierta: mientras esté abierta, la app sigue recogiendo datos. Si la cierras, el seguimiento se pausa y continúa al volver a abrirla (el histórico de velas se rellena solo).

No hace falta instalar nada más: solo usa la librería estándar de Python. Los datos se guardan en `memetracker.db` (SQLite) dentro de la carpeta.

En Mac o Linux: `./run.sh`.

## Fuentes de datos (gratis y sin clave)

| Dato | Fuente |
|---|---|
| Precio, liquidez, volumen, txns, market cap, redes | DexScreener |
| Velas OHLCV (histórico para análisis técnico), holders, top 10, descripción | GeckoTerminal |
| Seguridad Solana (mint/freeze, LP, riesgos, insiders) | RugCheck |
| Seguridad EVM (honeypot, impuestos, owner, LP bloqueada) | GoPlus |
| Holders y wallets únicas 24h (opcional) | Birdeye, si pones `birdeye_api_key` en `config.json` |

## Ajustes (`config.json`)

- `market_interval_sec`: cada cuánto guarda precio y mercado (300 = 5 min).
- `info_interval_sec`: holders y seguridad (1800 = 30 min).
- `ohlcv_interval_sec`: velas (900 = 15 min).
- `move_threshold_pct`: tamaño mínimo de una subida o bajada para registrarla como evento (20%).
- `live_move_pct`, `liquidity_drop_pct`, `holders_change_pct`: umbrales de las alertas en vivo.
- `port`: puerto de la web local.

GeckoTerminal permite unas 30 llamadas por minuto. Con los ajustes por defecto, la app va bien hasta unas 40 o 50 coins a la vez.

## Probar sin internet

`python tests/mock_apis.py` levanta APIs simuladas en el puerto 9999. Apunta `base_urls` en un config de prueba a `http://127.0.0.1:9999/{ds,gt,rc,gp}` y usa `MEMETRACKER_CONFIG=ruta/config.json`.

> Las puntuaciones (tendencia, sentimiento, salud) son heurísticas automáticas, no consejo de inversión.
