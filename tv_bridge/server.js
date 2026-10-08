/**
 * Bridge HTTP entre le backtester Python et @mathieuc/tradingview.
 * GET /health
 * GET /ohlcv?symbol=BTC&kind=crypto&quote=USDT&timeframe=1h&since=...&until=...
 *
 * Les cookies du compte se lisent dans tv_bridge/.env (TV_SESSION, TV_SIGNATURE).
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { getCandles, searchMarkets } from '@mathieuc/tradingview';

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || '0.0.0.0';

const TIMEFRAMES = {
  '1m': '1',
  '3m': '3',
  '5m': '5',
  '15m': '15',
  '30m': '30',
  '1h': '60',
  '2h': '120',
  '4h': '240',
  '1d': 'D',
  '1w': 'W',
  '1': '1',
  '3': '3',
  '5': '5',
  '15': '15',
  '30': '30',
  '60': '60',
  '120': '120',
  '240': '240',
  'D': 'D',
  '1D': 'D',
  'W': 'W',
  '1W': 'W',
};

const STEP_SECONDS = {
  '1': 60,
  '3': 180,
  '5': 300,
  '15': 900,
  '30': 1800,
  '60': 3600,
  '120': 7200,
  '240': 14400,
  'D': 86400,
  'W': 604800,
};

const STOCK_EXCHANGES = ['NASDAQ', 'NYSE', 'AMEX', 'NYSE ARCA', 'ARCA', 'BATS'];

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const text = fs.readFileSync(filePath, 'utf8');
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

const here = path.dirname(fileURLToPath(import.meta.url));
loadEnvFile(path.join(here, '.env'));

function credentials() {
  const session = process.env.TV_SESSION || process.env.SESSION || '';
  const signature = process.env.TV_SIGNATURE || process.env.SIGNATURE || '';
  if (!session) return undefined;
  return signature ? { session, signature } : { session };
}

function send(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function authorized(req) {
  const expected = process.env.TV_BRIDGE_TOKEN;
  if (!expected) return true;
  const header = req.headers.authorization || '';
  return header === `Bearer ${expected}`;
}

function mapTimeframe(value) {
  const raw = String(value || '1d').trim();
  const mapped = TIMEFRAMES[raw] || TIMEFRAMES[raw.toLowerCase()];
  if (!mapped) {
    throw Object.assign(new Error(`Timeframe non supporté: ${raw}`), { status: 400 });
  }
  return mapped;
}

async function resolveSymbol({ symbol, quote, kind, venue }) {
  const raw = String(symbol || '').trim().toUpperCase();
  if (!raw) {
    throw Object.assign(new Error('Symbole manquant.'), { status: 400 });
  }
  if (raw.includes(':')) return raw;

  if (kind === 'stock') {
    const markets = await searchMarkets(raw, { type: 'stock' });
    const exact = markets.filter((market) => String(market.symbol || '').toUpperCase() === raw);
    const pool = exact.length ? exact : markets;
    pool.sort((a, b) => {
      const rank = (market) => {
        const name = String(market.exchange || market.fullExchange || '').toUpperCase();
        const index = STOCK_EXCHANGES.findIndex((item) => name.includes(item));
        return index === -1 ? 99 : index;
      };
      return rank(a) - rank(b);
    });
    const chosen = pool[0];
    if (!chosen) {
      throw Object.assign(new Error(`Aucune action TradingView pour ${raw}.`), { status: 404 });
    }
    if (chosen.id) return String(chosen.id);
    const exchange = chosen.exchange || 'NASDAQ';
    return `${exchange}:${chosen.symbol || raw}`;
  }

  const base = raw.replace(/[^A-Z0-9]/g, '');
  let priced = String(quote || 'USDT').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const exchange = String(venue || 'BINANCE').toUpperCase();
  if (exchange === 'BINANCE' && priced === 'USD') priced = 'USDT';
  return `${exchange}:${base}${priced}`;
}

let tail = Promise.resolve();

function enqueue(task) {
  const run = tail.then(task, task);
  tail = run.then(() => undefined, () => undefined);
  return run;
}

async function loadCandles(query) {
  const timeframe = mapTimeframe(query.timeframe);
  const sinceSec = Math.floor(Number(query.since) / 1000);
  const untilSec = Math.floor(Number(query.until) / 1000);
  if (!Number.isFinite(sinceSec) || !Number.isFinite(untilSec) || sinceSec >= untilSec) {
    throw Object.assign(new Error('Fenêtre since/until invalide (millisecondes).'), { status: 400 });
  }

  const kind = String(query.kind || 'crypto').toLowerCase() === 'stock' ? 'stock' : 'crypto';
  const symbol = await resolveSymbol({
    symbol: query.symbol,
    quote: query.quote,
    kind,
    venue: query.venue,
  });
  const step = STEP_SECONDS[timeframe] || 3600;
  const estimated = Math.ceil((untilSec - sinceSec) / step) + 5;
  const maxCount = Math.min(120000, Math.max(estimated, 10));
  const timeoutMs = Math.min(300000, 20000 + estimated * 20);
  const creds = credentials();

  const candles = await getCandles({
    symbol,
    timeframe,
    from: sinceSec,
    to: untilSec,
    maxCount,
    adjustment: 'splits',
    ...(kind === 'stock' ? { session: 'regular' } : {}),
    ...(creds ? { credentials: creds } : {}),
    timeoutMs,
  });

  const rows = candles
    .filter((candle) => candle.time >= sinceSec && candle.time <= untilSec)
    .map((candle) => ({
      time: candle.time,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      volume: candle.volume ?? 0,
    }));

  const oldest = rows[0]?.time;
  const truncated = oldest !== undefined && oldest > sinceSec + step * 2 && rows.length >= maxCount - 5;

  return {
    symbol,
    timeframe,
    kind,
    authenticated: Boolean(creds),
    truncated,
    candles: rows,
  };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    send(res, 200, {
      status: 'ok',
      authenticated: Boolean(credentials()),
    });
    return;
  }

  if (req.method === 'GET' && url.pathname === '/ohlcv') {
    if (!authorized(req)) {
      send(res, 401, { error: 'Jeton TV_BRIDGE_TOKEN refusé.' });
      return;
    }
    try {
      const body = await enqueue(() => loadCandles({
        symbol: url.searchParams.get('symbol'),
        quote: url.searchParams.get('quote'),
        kind: url.searchParams.get('kind'),
        venue: url.searchParams.get('venue'),
        timeframe: url.searchParams.get('timeframe'),
        since: url.searchParams.get('since'),
        until: url.searchParams.get('until'),
      }));
      send(res, 200, body);
    } catch (error) {
      const status = error.status || (error.code === 'NO_DATA' ? 404 : 502);
      send(res, status, { error: error.message || String(error), code: error.code || 'FETCH_FAIL' });
    }
    return;
  }

  send(res, 404, { error: 'Route inconnue.' });
});

server.listen(PORT, HOST, () => {
  const auth = credentials() ? 'compte connecté' : 'accès anonyme';
  console.log(`TradingView bridge sur http://${HOST}:${PORT} (${auth})`);
});
