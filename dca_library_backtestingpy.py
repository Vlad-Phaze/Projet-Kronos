"""
Fichier autonome pour la stratégie DCA (Dollar Cost Averaging)
Combine main.py et dca_strategy.py en un seul fichier exécutable
"""

import os 
import json
import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy
import pandas_ta as ta
import yfinance as yf

class DCAStrategy(Strategy):
    """Stratégie DCA avec RSI, Bollinger Bands et Safety Orders"""
    
    # Paramètres par défaut
    rsi_length = 14
    rsi_entry = 30
    rsi_exit = 75
    bb_length = 20
    bb_std = 3
    bbp_trigger = 0.2
    min_tp = 0.01
    so_max = 4
    so_step = 0.0021  # distance en % entre chaque
    so_volume_scale = 1  # taille croissante
    so_step_scale = 1  # facteur exponentielle de l'ecart
    direction = 'long'
    start_time = pd.Timestamp("2024-01-01 00:00:00")
    end_time = pd.Timestamp("2030-01-01 00:00:00")
    use_mfi = False
    use_macd = False
    use_ema = False

    def init(self):
        """Initialisation de la stratégie"""
        # Données de clôture et timestamps
        close = self.data.Close
        self.timestamps = self.data.index.tz_localize(None)  # rendu tz naive pr bug yf

        # Calcul RSI
        def safe_rsi():
            rsi = ta.rsi(pd.Series(close), length=self.rsi_length)
            return rsi.fillna(0).to_numpy()

        # Calcul BB%
        def safe_bbp():
            bb = ta.bbands(pd.Series(close), length=self.bb_length, std=self.bb_std)
            # Vérifier les noms de colonnes disponibles
            print("Colonnes BB disponibles:", bb.columns.tolist())
            # Utiliser les noms de colonnes dynamiques
            lower_col = [col for col in bb.columns if 'BBL' in col][0]
            upper_col = [col for col in bb.columns if 'BBU' in col][0]
            bbp = (pd.Series(close) - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
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
        """Logique de trading à chaque barre"""
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
                step_scaled = self.so_step * (self.so_step_scale ** len(self.safety_orders))  # ecart entre SO
                price_deviation = abs((last_so_price - price) / last_so_price)  # check mouvement prix depuis last SO

                bbp_ok = bbp < self.bbp_trigger if self.position.is_long else bbp > (1 - self.bbp_trigger)  # check si zone basse
                deviation_ok = price_deviation >= step_scaled  # check deviation

                # Si toutes les conditions sont réunies on place un SO
                if deviation_ok and bbp_ok:
                    qty = 1 * (self.so_volume_scale ** len(self.safety_orders))
                    self.buy(size=qty) if self.position.is_long else self.sell(size=qty)
                    self.total_cost += price * qty
                    self.total_qty += qty
                    self.safety_orders.append(price)
                    print(f"Safety Order #{len(self.safety_orders)} à {price:.2f}")


def main():
    """Fonction principale pour exécuter le backtest"""
    
    # Paramètres de test (remplace le fichier params.json)
    start_date = "2023-09-27"
    end_date = "2025-09-25"
    
    # Téléchargement des données BTC-USD
    print("Téléchargement des données BTC-USD...")
    data = yf.download("BTC-USD", start="2023-09-27", end="2025-09-25", interval="1d")
    print(f"Données téléchargées: {len(data)} lignes")
    
    # Sauvegarde temporaire des données
    print("Sauvegarde des données...")
    data.to_csv("btc_data_temp.csv")
    
    # Lecture + nettoyage des données
    df = pd.read_csv("btc_data_temp.csv", index_col=0, skiprows=2, parse_dates=True)  # le skiprows pck le df a une ligne ticker en str
    
    # Vérifier et ajuster les colonnes selon ce qui est disponible
    print("Colonnes disponibles:", df.columns.tolist())
    print("Nombre de colonnes:", len(df.columns))
    
    # Ajuster les noms de colonnes selon le nombre disponible
    if len(df.columns) == 6:
        df.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        # Supprimer la colonne Adj Close si elle existe
        df = df.drop('Adj Close', axis=1)
    elif len(df.columns) == 5:
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    else:
        # Garder les colonnes telles quelles si elles correspondent déjà
        pass
    
    df = df.dropna()  # supprimer les lignes avec des NaN
    
    # Backtest
    print("Démarrage du backtest...")
    print(f"Données chargées: {len(df)} lignes")
    print(f"Période: {df.index[0]} à {df.index[-1]}")
    print(f"Prix de clôture: {df['Close'].iloc[0]:.2f} à {df['Close'].iloc[-1]:.2f}")
    
    bt = Backtest(df, DCAStrategy, cash=1_000_000, commission=.002)
    print("Lancement du backtest...")
    stats = bt.run()
    print("Résultats du backtest:")
    print(stats)
    print("Génération du graphique...")
    bt.plot()
    
    # Nettoyage du fichier temporaire
    if os.path.exists("btc_data_temp.csv"):
        os.remove("btc_data_temp.csv")
        print("Fichier temporaire supprimé")


if __name__ == "__main__":
    main()
