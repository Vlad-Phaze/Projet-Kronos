# strategies/buy_dip.py
import pandas as pd
from typing import Dict, Any
from datafeed_tester.core.types import BaseStrategy
try:
    import pandas_ta as ta
except Exception:
    # Lightweight fallback for environments where pandas_ta is not available.
    # We only implement the small subset used by this strategy: rsi and bbands.
    class _SimpleTA:
        @staticmethod
        def rsi(series, length=14):
            # Wilder's RSI approximation using exponential moving averages
            delta = series.diff()
            up = delta.clip(lower=0.0)
            down = -delta.clip(upper=0.0)
            # Use simple rma / ema-like smoothing
            ma_up = up.ewm(alpha=1/length, adjust=False).mean()
            ma_down = down.ewm(alpha=1/length, adjust=False).mean()
            rs = ma_up / ma_down.replace(0, 1e-8)
            rsi = 100 - 100 / (1 + rs)
            return rsi

        @staticmethod
        def bbands(series, length=20, std=2):
            ma = series.rolling(window=length, min_periods=1).mean()
            sd = series.rolling(window=length, min_periods=1).std(ddof=0)
            upper = ma + std * sd
            lower = ma - std * sd
            # pandas_ta returns a DataFrame with keys like 'BBL_20_3.0' and 'BBU_20_3.0'
            key_low = f"BBL_{length}_{float(std)}"
            key_up = f"BBU_{length}_{float(std)}"
            return {key_low: lower, key_up: upper}

    ta = _SimpleTA()
import numpy as np

class DCAStrategy(BaseStrategy):
    # Paramètres par défaut (modifiés par Streamlit)
    rsi_length = 14
    rsi_entry = 30
    rsi_exit = 75
    bb_length = 20
    bb_std = 3
    bbp_trigger = 0.2
    min_tp = 0.01
    so_max = 4
    so_step = 0.0021 #distance en % entre chaque
    so_volume_scale = 1 #taille croissante
    so_step_scale = 1 #facteur exponentielle de l'ecart
    direction = 'long'
    start_time = pd.Timestamp("2024-01-01 00:00:00") #voir si utile
    end_time = pd.Timestamp("2030-01-01 00:00:00") #voir si utile
    use_mfi = False
    use_macd = False
    use_ema = False

    def init(self):
        # Données de clôture et timestamps
        close = self.data.Close
        self.timestamps = self.data.index.tz_localize(None) #rendu tz naive pr bug yf

        # Calcul RSI
        def safe_rsi():
            rsi = ta.rsi(pd.Series(close), length=self.rsi_length)
            return rsi.fillna(0).to_numpy()

        # Calcul BB%
        def safe_bbp():
            bb = ta.bbands(pd.Series(close), length=self.bb_length, std=self.bb_std)
            bbp = (pd.Series(close) - bb['BBL_20_3.0']) / (bb['BBU_20_3.0'] - bb['BBL_20_3.0'])
            return bbp.fillna(0).to_numpy()

        # application des indicateurs
        self.rsi = self.I(safe_rsi)
        self.bbp = self.I(safe_bbp)

        # variables ordres / safety orders
        self.entry_price = None
        self.total_cost = 0
        self.total_qty = 0
        self.safety_orders = []

    def next(self):
        # dernière valeur: prix, indicateurs, temps
        price = self.data.Close[-1]
        rsi = self.rsi[-1]
        bbp = self.bbp[-1]
        timestamp = self.timestamps[-1]

        # période définie pour trader (a sup potentiellement)
        if timestamp < self.start_time or timestamp > self.end_time:
            return

        # déclenchement entrée
        if not self.position:
            if self.direction == 'long' and rsi < self.rsi_entry:
                self.buy()
                self.entry_price = price
                self.total_cost = price
                self.total_qty = 1
                self.safety_orders = [price]
                print(f"[LONG] Entrée à {price:.2f}")
            elif self.direction == 'short' and rsi > self.rsi_exit:
                self.sell()
                self.entry_price = price
                self.total_cost = price
                self.total_qty = 1
                self.safety_orders = [price]
                print(f"[SHORT] Entrée à {price:.2f}")

        # Gestion de la position en cours
        elif self.position:
            avg_price = self.total_cost / self.total_qty
            pnl = ((price - avg_price) / avg_price) if self.position.is_long else ((avg_price - price) / avg_price)

            # Conditions de sortie : RSI + Take Profit minimum
            if (self.position.is_long and rsi > self.rsi_exit and pnl >= self.min_tp) or \
               (self.position.is_short and rsi < self.rsi_entry and pnl >= self.min_tp):
                self.position.close()
                print(f"Sortie à {price:.2f} | PnL: {pnl * 100:.2f}%")

            # Déclenchement Safety orders
            if len(self.safety_orders) < self.so_max:
                last_so_price = self.safety_orders[-1]
                step_scaled = self.so_step * (self.so_step_scale ** len(self.safety_orders)) #ecart entre SO
                price_deviation = abs((last_so_price - price) / last_so_price) #check mouvement prix depuis last SO

                bbp_ok = bbp < self.bbp_trigger if self.position.is_long else bbp > (1 - self.bbp_trigger) # check si zone basse
                deviation_ok = price_deviation >= step_scaled #check deviation

                # Si toutes les conditions sont réunies on place un SO
                if deviation_ok and bbp_ok:
                    qty = 1 * (self.so_volume_scale ** len(self.safety_orders))
                    self.buy(size=qty) if self.position.is_long else self.sell(size=qty)
                    self.total_cost += price * qty
                    self.total_qty += qty
                    self.safety_orders.append(price)
                    print(f"Safety Order #{len(self.safety_orders)} à {price:.2f}")

    def generate_signals(self, df, params):
        # On utilise la logique d'entrée de ta stratégie :
        # Signal 'long' si RSI < rsi_entry, sinon 'flat'
        rsi = ta.rsi(df['close'], length=self.rsi_length if hasattr(self, 'rsi_length') else 14)
        signals = pd.DataFrame(index=df.index)
        signals['side'] = np.where(rsi < self.rsi_entry if hasattr(self, 'rsi_entry') else 30, 'long', 'flat')
        print("[DEBUG] Signaux générés:", signals['side'].value_counts())
        print("[DEBUG] Premieres valeurs RSI:", rsi.head(10).to_list())
        print("[DEBUG] Premieres valeurs close:", df['close'].head(10).to_list())
        return signals
# Fonction attendue par l'API Flask
def build_strategy(broker, data, params):
    return DCAStrategy(broker, data, params)
