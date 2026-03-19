import numpy as np
import pandas as pd
from typing import Dict, Any

try:
    import vectorbt as vbt
except ImportError:
    vbt = None

try:
    import ccxt
except ImportError:
    ccxt = None


def ma_crossover_vectorbt(
    close: pd.Series,
    fast: int = 10,
    slow: int = 30,
    fees: float = 0.0005,
    slippage: float = 0.0002,
    long_short: bool = False,
    init_cash: float = 10_000,
    freq: str | None = "1D"
):
    """Fonction standalone pour backtester une stratégie MA crossover avec vectorbt."""
    if vbt is None:
        raise RuntimeError("vectorbt is not installed")
    
    if fast >= slow:
        raise ValueError("fast must be < slow for a basic crossover setup.")

    close = close.dropna()
    if not isinstance(close.index, (pd.DatetimeIndex, pd.PeriodIndex)):
        raise ValueError("close index must be a DatetimeIndex (or PeriodIndex).")

    fast_ma = vbt.MA.run(close, window=fast, ewm=False).ma
    slow_ma = vbt.MA.run(close, window=slow, ewm=False).ma

    long_entries = fast_ma.vbt.crossed_above(slow_ma)
    long_exits = fast_ma.vbt.crossed_below(slow_ma)

    if not long_short:
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=long_entries,
            exits=long_exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            freq=freq
        )
    else:
        short_entries = long_exits
        short_exits = long_entries

        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=long_entries,
            exits=long_exits,
            short_entries=short_entries,
            short_exits=short_exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            freq=freq
        )

    signals_df = pd.DataFrame({
        "close": close,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "long_entries": long_entries,
        "long_exits": long_exits
    })

    return pf, signals_df


def load_binance_data(symbol: str, start: str, end: str, timeframe: str = '1d'):
    """Charge les données OHLCV depuis Binance via ccxt."""
    if ccxt is None:
        raise RuntimeError("ccxt is not installed")
    
    try:
        print(f"Récupération des données {symbol} depuis Binance...")
        
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        
        start_timestamp = int(pd.Timestamp(start).timestamp() * 1000)
        end_timestamp = int(pd.Timestamp(end).timestamp() * 1000)
        
        all_ohlcv = []
        current_timestamp = start_timestamp
        
        max_limit = 1000
        
        print(f"Période: {start} à {end}")
        
        while current_timestamp < end_timestamp:
            ohlcv = exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=current_timestamp,
                limit=max_limit
            )
            
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            
            last_timestamp = ohlcv[-1][0]
            
            if len(ohlcv) < max_limit:
                break
            
            if last_timestamp <= current_timestamp:
                break
                
            current_timestamp = last_timestamp + 1
            
            exchange.sleep(100)
        
        if not all_ohlcv:
            raise RuntimeError(f"Aucune donnée récupérée pour {symbol}")
        
        df = pd.DataFrame(
            all_ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        df = df.loc[start:end]
        
        close = df['close'].copy()
        
        if not isinstance(close.index, pd.DatetimeIndex):
            close.index = pd.to_datetime(close.index)
        
        if close.index.tz is not None:
            close.index = close.index.tz_convert(None)
        
        print(f"Données récupérées: {len(close)} points de {close.index.min()} à {close.index.max()}")
        
        return close.dropna()
        
    except ccxt.BaseError as e:
        raise RuntimeError(f"Erreur CCXT lors du téléchargement depuis Binance: {e}")
    except Exception as e:
        raise RuntimeError(f"Erreur lors du téléchargement des données Binance: {e}")


# ============================================================================
# ADAPTER POUR LE RUNNER (génération de signaux compatibles)
# ============================================================================

class MACrossoverStrategy:
    """Adapter pour le runner multi_vectorbt.
    
    Expose generate_signals(df, params) -> DataFrame avec colonne 'side'.
    """
    
    fast: int = 10
    slow: int = 30
    
    def __init__(self, *args, **kwargs):
        # Accept arbitrary args for compatibility
        pass
    
    def generate_signals(self, df: pd.DataFrame, params: Dict[str, Any] | None = None) -> pd.DataFrame:
        """Génère des signaux de trading à partir d'un DataFrame OHLCV.
        
        Args:
            df: DataFrame avec au moins une colonne 'close'
            params: Paramètres optionnels (fast, slow)
        
        Returns:
            DataFrame avec colonne 'side' ('long' ou 'flat')
        """
        params = params or {}
        fast = int(params.get("fast", self.fast))
        slow = int(params.get("slow", self.slow))
        
        # Extraire la série close
        if "close" not in df.columns:
            if "Close" in df.columns:
                close = df["Close"].astype(float)
            elif df.shape[1] >= 1:
                close = df.iloc[:, 0].astype(float)
                close.name = "close"
            else:
                raise ValueError("DataFrame must contain a 'close' column")
        else:
            close = df["close"].astype(float)
        
        close = close.dropna()
        if close.empty:
            return pd.DataFrame(index=df.index)
        
        # Calculer les moyennes mobiles EXACTEMENT comme la version standalone
        # ⚠️ IMPORTANT: min_periods=window pour éviter les signaux précoces
        fast_ma = close.rolling(window=fast, min_periods=fast).mean()
        slow_ma = close.rolling(window=slow, min_periods=slow).mean()
        
        # Détecter les croisements
        long_entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        long_exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        
        # Construire le DataFrame de signaux
        signals = pd.DataFrame(index=close.index)
        signals["long_entries"] = long_entries.fillna(False)
        signals["long_exits"] = long_exits.fillna(False)
        signals["fast_ma"] = fast_ma
        signals["slow_ma"] = slow_ma
        signals["close"] = close
        
        # Reindex to match input
        signals = signals.reindex(df.index)
        
        # ⚠️ CORRECTION MAJEURE: maintenir 'long' JUSQU'à la sortie, pas seulement à l'entrée!
        # Créer un état qui persiste entre entry et exit
        out = pd.DataFrame(index=df.index)
        position = 0  # 0 = flat, 1 = long
        side_values = []
        
        for idx in df.index:
            if idx in signals.index:
                if signals.loc[idx, 'long_entries']:
                    position = 1  # Entrer en position
                elif signals.loc[idx, 'long_exits']:
                    position = 0  # Sortir de position
            side_values.append('long' if position == 1 else 'flat')
        
        out["side"] = side_values
        
        return out


def build_strategy(broker, data, params: Dict[str, Any] | None = None):
    """Compatibility shim pour l'API Flask."""
    class Wrapper:
        def __init__(self, params):
            self.params = params or {}
        
        def generate_signals(self, df, p=None):
            merged = dict(self.params or {})
            if p:
                merged.update(p)
            return MACrossoverStrategy().generate_signals(df, merged)
    
    return Wrapper(params)


# ============================================================================
# SCRIPT STANDALONE
# ============================================================================

def main():
    """Point d'entrée pour exécution standalone."""
    symbol = "BTC/USDT"
    start = "2023-01-01"
    end = "2024-01-01"
    timeframe = "1h"
    
    close = load_binance_data(symbol, start, end, timeframe=timeframe)
    
    if close.empty:
        raise RuntimeError("No data downloaded. Check symbol, dates, or internet access.")

    pf, signals = ma_crossover_vectorbt(
        close=close,
        fast=10,
        slow=30,
        fees=0.0005,
        slippage=0.0002,
        long_short=False,
        init_cash=10_000,
        freq="1H"
    )

    print("\n=== STATS ===")
    print(pf.stats())

    print("\n=== FIRST TRADES (if any) ===")
    try:
        print(pf.trades.records_readable.head(10))
    except Exception:
        print("No trades (or trades table not available).")

    pf.plot().show()


if __name__ == "__main__":
    main()
