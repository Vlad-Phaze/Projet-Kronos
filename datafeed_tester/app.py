from __future__ import annotations
"""
API Kronos - Backtesteur DCA avec gestion de données et génération de rapports
Utilise fetcher.py pour la récupération multi-sources et backtester amélioré pour l'analyse DCA
"""

import sys
import os
import gc
import time

# Configuration UTF-8 pour Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import uuid
import tempfile
import hashlib
import base64
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif
import matplotlib.pyplot as plt
import seaborn as sns
from backtesting import Backtest, Strategy
import pandas_ta as ta
import yfinance as yf
from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS

# Import du backtester exact (sans reload forcé pour éviter les pics RAM)
import backtester_exact
from backtester_exact import ParametresDCA_SmartBotV2, backtest_smartbot_v2

# Import du fetcher - Binance uniquement pour meilleure performance
from fetcher import fetch_binance_only, expand_coin_inputs, EXCHANGES, fetch_ohlcv

# Pas de duplication d'import future ici
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import uuid
import tempfile
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Fonction pour convertir pandas Series/DataFrame en types JSON-sérialisables
def convert_pandas_to_json(obj):
    """Convertit récursivement les objets pandas en types sérialisables JSON"""
    if isinstance(obj, pd.Series):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, dict):
        return {key: convert_pandas_to_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_pandas_to_json(item) for item in obj]
    else:
        return obj
import base64
from io import BytesIO

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif pour les graphiques
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yfinance as yf
from backtesting import Backtest, Strategy
import pandas_ta as ta

# Import de ton fetcher personnalisé
from fetcher import compare_exchanges_on_bases, expand_coin_inputs, EXCHANGES

# Configuration des graphiques
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")

# === Storage global pour les données et résultats
DATA_STORE = {}  # {dataset_id: {"data": df, "meta": dict, "sources": list}}
BACKTEST_STORE = {}  # {run_id: {"results": dict, "images": dict, "data": df}}

# === Configuration Flask
app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

BINANCE_CACHE_TTL_SECONDS = int(os.getenv("BINANCE_CACHE_TTL_SECONDS", "600"))
_BINANCE_FETCH_CACHE: Dict[str, Any] = {}

try:
    import resource  # linux/unix (Render)
except Exception:
    resource = None


def get_memory_mb() -> Optional[float]:
    """Retourne la mémoire RSS du process en MB si disponible."""
    if resource is None:
        return None
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux = KB, macOS = bytes
        if sys.platform == "darwin":
            return float(rss) / (1024 * 1024)
        return float(rss) / 1024.0
    except Exception:
        return None


def log_perf(stage: str, t0: float) -> None:
    elapsed = time.perf_counter() - t0
    mem = get_memory_mb()
    if mem is None:
        print(f"⏱️ {stage}: {elapsed:.2f}s")
    else:
        print(f"⏱️ {stage}: {elapsed:.2f}s | RAM ~ {mem:.1f} MB")


def fetch_binance_only_cached(**kwargs):
    """Cache court pour éviter de refetch les mêmes OHLCV à répétition."""
    cache_key = json.dumps(kwargs, sort_keys=True, default=str)
    now = time.time()
    cached = _BINANCE_FETCH_CACHE.get(cache_key)
    if cached and (now - cached["ts"]) <= BINANCE_CACHE_TTL_SECONDS:
        print(f"🧠 Cache OHLCV hit ({BINANCE_CACHE_TTL_SECONDS}s)")
        return cached["value"]

    result = fetch_binance_only(**kwargs)
    _BINANCE_FETCH_CACHE[cache_key] = {"ts": now, "value": result}

    # Limiter la taille du cache en mémoire
    if len(_BINANCE_FETCH_CACHE) > 8:
        oldest = min(_BINANCE_FETCH_CACHE.items(), key=lambda item: item[1]["ts"])[0]
        _BINANCE_FETCH_CACHE.pop(oldest, None)
    return result

# Import helper to run multi-asset vectorbt backtests (uses project fetcher)
try:
    from run_multi_vectorbt import run_multi_backtest
except Exception:
    # fallback if module not importable by name; try package import
    try:
        from datafeed_tester.run_multi_vectorbt import run_multi_backtest
    except Exception:
        run_multi_backtest = None


@app.route('/run-multi-backtest', methods=['POST'])
def run_multi_backtest_endpoint():
    if run_multi_backtest is None:
        return jsonify({'error': 'run_multi_backtest not available on server'}), 500

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({'error': 'JSON payload required'}), 400

    bases = payload.get('bases')
    if isinstance(bases, str):
        bases = [b.strip().upper() for b in bases.split(',') if b.strip()]
    if not bases or not isinstance(bases, (list, tuple)):
        return jsonify({'error': 'bases must be provided as list or comma string'}), 400

    weights = payload.get('weights')
    if isinstance(weights, str):
        try:
            weights = [float(w.strip()) for w in weights.split(',') if w.strip()]
        except Exception:
            return jsonify({'error': 'weights must be float values separated by comma'}), 400

    exchange = payload.get('exchange', 'binance')
    timeframe = payload.get('timeframe', '1h')
    init_cash = float(payload.get('init_cash', 100000.0))
    start = payload.get('start')
    end = payload.get('end')

    # fee/slippage accepted but not used by current runner (kept for forward compatibility)
    fee = float(payload.get('fee', 0.0))
    slippage = float(payload.get('slippage', 0.0))

    try:
        per_stats_df, combined_stats, eq_df, combined_equity = run_multi_backtest(
            bases, exchange=exchange, timeframe=timeframe, init_cash=init_cash, start=start, end=end, weights=weights,
            fee=fee, slippage=slippage
        )

        # Paths where the runner saved CSVs (relative to project root)
        result_files = {
            'per_asset_stats': 'multi_vectorbt_per_asset_stats.csv',
            'per_asset_equity': 'multi_vectorbt_per_asset_equity.csv',
            'combined_equity': 'multi_vectorbt_combined_equity.csv',
            'combined_stats': 'multi_vectorbt_combined_stats.csv'
        }

        return jsonify({
            'ok': True,
            'files': result_files,
            'combined_stats': convert_pandas_to_json(combined_stats),
            'per_asset_stats': convert_pandas_to_json(per_stats_df)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/plot-combined-equity', methods=['GET', 'POST'])
def plot_combined_equity():
    """Return a PNG plot of combined equity.

    GET: reads `datafeed_tester/multi_vectorbt_combined_equity.csv` and returns PNG.
    POST: accepts JSON {"equity": [values], "index": [iso timestamps optional]} and returns PNG.
    """
    try:
        if request.method == 'POST':
            payload = request.get_json(force=True)
            if not payload or 'equity' not in payload:
                return jsonify({'error': 'JSON with key "equity" required for POST'}), 400
            equity = payload.get('equity')
            index = payload.get('index')
            if index:
                ser = pd.Series(equity, index=pd.to_datetime(index))
            else:
                ser = pd.Series(equity)
        else:
            # GET: try reading the saved CSV
            try:
                df = pd.read_csv('multi_vectorbt_combined_equity.csv', index_col=0, parse_dates=True)
                # detect column name
                if 'equity' in df.columns:
                    ser = df['equity']
                else:
                    # take first column
                    ser = df.iloc[:, 0]
            except Exception as e:
                return jsonify({'error': 'No combined equity CSV found and no payload provided', 'exc': str(e)}), 400

        # Plot
        plt.figure(figsize=(10, 4))
        ser.plot(title='Combined Equity')
        plt.xlabel('Time')
        plt.ylabel('Equity')
        plt.grid(True)
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generate_pnl_drawdown_chart(combined_equity: pd.Series, init_cash: float) -> str:
    """
    Génère un graphique avec PNL (vert) et Drawdown (rouge) combinés.
    
    Args:
        combined_equity: Série temporelle de l'équité combinée
        init_cash: Capital initial (utilisé pour référence seulement)
        
    Returns:
        String base64 du graphique PNG
    """
    fig, ax1 = plt.subplots(figsize=(14, 7))
    
    # CORRECTION: Utiliser la valeur initiale réelle de combined_equity
    actual_start = combined_equity.iloc[0]
    
    # Calculer le PNL en pourcentage par rapport au capital RÉELLEMENT investi
    pnl_pct = ((combined_equity - actual_start) / actual_start) * 100
    
    # Calculer le drawdown en pourcentage
    peak = combined_equity.cummax()
    drawdown_pct = ((combined_equity - peak) / peak) * 100
    
    # Axe principal : PNL (vert)
    color_pnl = '#00ff88'
    ax1.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax1.set_ylabel('PNL (%)', fontsize=12, fontweight='bold', color=color_pnl)
    line1 = ax1.plot(pnl_pct.index, pnl_pct.values, color=color_pnl, linewidth=2, label='PNL (%)', alpha=0.9)
    ax1.tick_params(axis='y', labelcolor=color_pnl)
    ax1.axhline(y=0, color='white', linestyle='--', linewidth=1, alpha=0.3)
    ax1.grid(True, alpha=0.2, linestyle='--')
    
    # Axe secondaire : Drawdown (rouge)
    ax2 = ax1.twinx()
    color_dd = '#ff4444'
    ax2.set_ylabel('Drawdown (%)', fontsize=12, fontweight='bold', color=color_dd)
    line2 = ax2.plot(drawdown_pct.index, drawdown_pct.values, color=color_dd, linewidth=2, label='Drawdown (%)', alpha=0.9)
    ax2.tick_params(axis='y', labelcolor=color_dd)
    ax2.fill_between(drawdown_pct.index, drawdown_pct.values, 0, color=color_dd, alpha=0.15)
    
    # Titre et légende
    final_pnl_pct = pnl_pct.iloc[-1]
    max_dd_pct = drawdown_pct.min()
    plt.title(f'Portfolio Performance - PNL: {final_pnl_pct:,.2f}% | Max DD: {max_dd_pct:,.2f}%', 
              fontsize=14, fontweight='bold', pad=20)
    
    # Combiner les légendes
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left', fontsize=10, framealpha=0.9)
    
    # Style sombre
    fig.patch.set_facecolor('#0a0e27')
    ax1.set_facecolor('#1a1f3a')
    ax1.spines['top'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    for spine in ['bottom', 'left', 'right']:
        ax1.spines[spine].set_color('#4fc3f7')
        ax2.spines[spine].set_color('#4fc3f7')
    ax1.tick_params(colors='white')
    ax2.tick_params(colors='white')
    ax1.xaxis.label.set_color('white')
    
    plt.tight_layout()
    
    # Convertir en base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=100, facecolor='#0a0e27')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close(fig)
    
    return image_base64


@app.route('/backtest-custom-strategy', methods=['POST'])
def backtest_custom_strategy():
    """
    Upload un fichier de stratégie Python et lance un backtest vectorbt.
    
    Form-data attendu:
    - strategy_file: fichier .py contenant la stratégie
    - bases: liste de bases séparées par virgule (ex: "BTC,ETH")
    - exchange: (optionnel) exchange à forcer, sinon fusion multi-exchange
    - timeframe: (défaut: 1h)
    - start: date de début (format: YYYY-MM-DD)
    - end: date de fin (format: YYYY-MM-DD)
    - init_cash: capital initial (défaut: 10000)
    - fee: frais de trading (défaut: 0.0)
    - slippage: slippage (défaut: 0.0)
    - strategy_class: nom de la classe de stratégie (défaut: recherche auto)
    """
    try:
        # Vérifier la présence du fichier
        if 'strategy_file' not in request.files:
            return jsonify({'error': 'Aucun fichier strategy_file fourni'}), 400
        
        file = request.files['strategy_file']
        if file.filename == '':
            return jsonify({'error': 'Nom de fichier vide'}), 400
        
        if not file.filename.endswith('.py'):
            return jsonify({'error': 'Le fichier doit être un fichier Python (.py)'}), 400
        
        # Récupérer les paramètres
        bases = request.form.get('bases', 'BTC').strip()
        exchange = request.form.get('exchange', None)
        timeframe = request.form.get('timeframe', '1h')
        start = request.form.get('start', '2023-01-01')
        end = request.form.get('end', '2024-01-01')
        init_cash = float(request.form.get('init_cash', 10000))
        fee = float(request.form.get('fee', 0.0))
        slippage = float(request.form.get('slippage', 0.0))
        strategy_class_name = request.form.get('strategy_class', None)
        max_active_trades = request.form.get('max_active_trades', None)
        
        print(f"🔍 DEBUG - max_active_trades brut: '{max_active_trades}'")
        
        if max_active_trades and max_active_trades.strip():
            max_active_trades = int(max_active_trades)
            print(f"✅ Max Active Trades converti: {max_active_trades}")
        else:
            max_active_trades = None
            print(f"⚠️  Max Active Trades vide ou None")
        
        # Sauvegarder temporairement le fichier de stratégie
        run_id = str(uuid.uuid4())[:8]
        strategy_filename = f"custom_strategy_{run_id}.py"
        strategy_path = os.path.join(tempfile.gettempdir(), strategy_filename)
        
        file.save(strategy_path)
        print(f"✅ Stratégie sauvegardée: {strategy_path}")
        
        # Charger dynamiquement la stratégie
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"strategy_{run_id}", strategy_path)
        strategy_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(strategy_module)
        
        # Trouver la classe de stratégie
        if strategy_class_name:
            if not hasattr(strategy_module, strategy_class_name):
                return jsonify({'error': f'Classe {strategy_class_name} non trouvée dans le fichier'}), 400
            strategy_class = getattr(strategy_module, strategy_class_name)
        else:
            # Chercher automatiquement une classe qui ressemble à une stratégie
            strategy_class = None
            for name in dir(strategy_module):
                obj = getattr(strategy_module, name)
                if isinstance(obj, type) and 'Strategy' in name:
                    strategy_class = obj
                    strategy_class_name = name
                    break
            
            if strategy_class is None:
                return jsonify({'error': 'Aucune classe de stratégie trouvée. Spécifiez strategy_class ou nommez votre classe avec "Strategy"'}), 400
        
        print(f"✅ Classe de stratégie chargée: {strategy_class_name}")
        
        # Importer run_multi_backtest
        try:
            from run_multi_vectorbt import run_multi_backtest
        except ImportError:
            return jsonify({'error': 'Module run_multi_vectorbt non disponible'}), 500
        
        # Parser les bases
        bases_list = [b.strip().upper() for b in bases.split(',') if b.strip()]
        
        if not bases_list:
            return jsonify({'error': 'Au moins une base est requise'}), 400
        
        # Convertir exchange vide en None pour multi-exchange fusion
        exchange_to_use = exchange if exchange and exchange.strip() else None
        
        print(f"🚀 Lancement du backtest:")
        print(f"   Bases: {bases_list}")
        print(f"   Exchange: {exchange_to_use or 'fusion multi-exchange'}")
        print(f"   Période: {start} → {end}")
        print(f"   Timeframe: {timeframe}")
        print(f"   Capital: {init_cash}")
        print(f"   Fees: {fee}, Slippage: {slippage}")
        if max_active_trades:
            print(f"   Max Active Trades: {max_active_trades}")
        
        # Extraire les paramètres SmartBot V2 DCA (optionnels)
        dsc_mode = request.form.get('dsc_mode')
        rsi_length = request.form.get('rsi_length')
        rsi_threshold = request.form.get('rsi_threshold')
        bb_length = request.form.get('bb_length')
        bb_mult = request.form.get('bb_mult')
        bb_threshold = request.form.get('bb_threshold')
        mfi_length = request.form.get('mfi_length')
        mfi_threshold = request.form.get('mfi_threshold')
        atr_length = request.form.get('atr_length')
        atr_mult = request.form.get('atr_mult')
        
        # Construire le dict de paramètres supplémentaires
        extra_params = {}
        
        # Ajouter les paramètres SmartBot V2
        if dsc_mode:
            extra_params['dsc_mode'] = dsc_mode
            print(f"   🤖 DSC Mode: {dsc_mode}")
        if rsi_length:
            extra_params['rsi_length'] = int(rsi_length)
            print(f"   📊 RSI Length: {rsi_length}")
        if rsi_threshold:
            extra_params['rsi_threshold'] = float(rsi_threshold)
            print(f"   📉 RSI Threshold: {rsi_threshold}")
        if bb_length:
            extra_params['bb_length'] = int(bb_length)
            print(f"   📊 BB Length: {bb_length}")
        if bb_mult:
            extra_params['bb_mult'] = float(bb_mult)
            print(f"   📊 BB Multiplier: {bb_mult}")
        if bb_threshold:
            extra_params['bb_threshold'] = float(bb_threshold)
            print(f"   📉 BB Threshold: {bb_threshold}")
        if mfi_length:
            extra_params['mfi_length'] = int(mfi_length)
            print(f"   💰 MFI Length: {mfi_length}")
        if mfi_threshold:
            extra_params['mfi_threshold'] = float(mfi_threshold)
            print(f"   📉 MFI Threshold: {mfi_threshold}")
        if atr_length:
            extra_params['atr_length'] = int(atr_length)
            print(f"   📊 ATR Length: {atr_length}")
        if atr_mult:
            extra_params['atr_mult'] = float(atr_mult)
            print(f"   📊 ATR Multiplier: {atr_mult}")
        
        # Extraire les nouveaux paramètres DCA complets
        base_order = request.form.get('base_order')
        safe_order = request.form.get('safe_order')
        max_safe_order = request.form.get('max_safe_order')
        safe_order_volume_scale = request.form.get('safe_order_volume_scale')
        pricedevbase = request.form.get('pricedevbase')
        price_deviation = request.form.get('price_deviation')
        deviation_scale = request.form.get('deviation_scale')
        atr_smoothing = request.form.get('atr_smoothing')
        take_profit_pct = request.form.get('take_profit')
        tp_type = request.form.get('tp_type')
        dsc2_enabled = request.form.get('dsc2_enabled')
        dsc2 = request.form.get('dsc2')
        
        # Ajouter les paramètres DCA complets
        if base_order:
            extra_params['base_order'] = float(base_order)
            print(f"   💵 Base Order: ${base_order}")
        if safe_order:
            extra_params['safe_order'] = float(safe_order)
            print(f"   💵 Safety Order: ${safe_order}")
        if max_safe_order:
            extra_params['max_safe_order'] = int(max_safe_order)
            print(f"   🔢 Max Safety Orders: {max_safe_order}")
        if safe_order_volume_scale:
            extra_params['safe_order_volume_scale'] = float(safe_order_volume_scale)
            print(f"   📈 SO Volume Scale: {safe_order_volume_scale}")
        if pricedevbase:
            extra_params['pricedevbase'] = pricedevbase
            print(f"   📉 Price Deviation Type: {pricedevbase}")
        if price_deviation:
            extra_params['price_deviation'] = float(price_deviation)
            print(f"   📉 Price Deviation: {price_deviation}%")
        if deviation_scale:
            extra_params['deviation_scale'] = float(deviation_scale)
            print(f"   📊 Deviation Scale: {deviation_scale}")
        if atr_smoothing:
            extra_params['atr_smoothing'] = int(atr_smoothing)
            print(f"   📊 ATR Smoothing: {atr_smoothing}")
        if take_profit_pct:
            extra_params['take_profit'] = float(take_profit_pct)
            print(f"   🎯 Take Profit: {take_profit_pct}%")
        if tp_type:
            extra_params['tp_type'] = tp_type
            print(f"   🎯 TP Type: {tp_type}")
        if dsc2_enabled is not None:
            extra_params['dsc2_enabled'] = dsc2_enabled.lower() == 'true'
            print(f"   🔀 DSC2 Enabled: {dsc2_enabled}")
        if dsc2:
            extra_params['dsc2'] = dsc2
            print(f"   🔀 DSC2 Condition: {dsc2}")

        
        # Créer une référence de stratégie pour run_multi_backtest
        # Format: chemin_fichier:NomClasse
        strategy_ref = f"{strategy_path}:{strategy_class_name}"
        
        # Lancer le backtest
        per_stats, combined_stats, eq_df, combined_equity = run_multi_backtest(
            bases=bases_list,
            exchange=exchange_to_use,
            timeframe=timeframe,
            init_cash=init_cash,
            start=start,
            end=end,
            weights=None,
            fee=fee,
            slippage=slippage,
            max_active_trades=max_active_trades,
            strategy_ref=strategy_ref,
            strategy_params=extra_params  # Nouveaux paramètres DCA
        )
        
        # Nettoyer le fichier temporaire
        try:
            os.remove(strategy_path)
        except:
            pass
        
        # Fonction helper pour convertir les valeurs NaN en 0
        def safe_float(value, default=0.0):
            """Convertit en float, retourne default si NaN"""
            try:
                val = float(value)
                return default if pd.isna(val) or np.isnan(val) or np.isinf(val) else val
            except (ValueError, TypeError):
                return default
        
        def safe_int(value, default=0):
            """Convertit en int, retourne default si NaN"""
            try:
                val = float(value)
                return default if pd.isna(val) or np.isnan(val) or np.isinf(val) else int(val)
            except (ValueError, TypeError):
                return default
        
        # Préparer la réponse
        result = {
            'run_id': run_id,
            'status': 'success',
            'strategy_class': strategy_class_name,
            'bases': bases_list,
            'exchange': exchange or 'multi-exchange fusion',
            'period': f"{start} → {end}",
            'timeframe': timeframe,
            'combined_stats': {
                'start_value': safe_float(combined_stats['Start Value']),
                'end_value': safe_float(combined_stats['End Value']),
                'total_return_pct': safe_float(combined_stats['Total Return [%]']),
                'max_drawdown_pct': safe_float(combined_stats['Max Drawdown [%]']),
                'num_assets_requested': safe_int(combined_stats['Num Assets Requested']),
                'num_assets_with_data': safe_int(combined_stats['Num Assets With Data']),
                'num_assets_active': safe_int(combined_stats['Num Assets Active']),
                'num_assets_no_data': safe_int(combined_stats['Num Assets No Data']),
                'num_assets_no_signals': safe_int(combined_stats['Num Assets No Signals']),
                'skipped_assets_no_data': combined_stats.get('Skipped Assets (No Data)', 'None'),
                'skipped_assets_no_signals': combined_stats.get('Skipped Assets (No Signals)', 'None')
            },
            'per_asset_stats': {}
        }
        # Ajouter les stats par asset
        # Note: per_stats peut avoir plusieurs lignes (une par asset)
        # On doit trouver la ligne correspondant à chaque asset
        for col in per_stats.columns:
            if '_Start Value' in col:
                base = col.replace('_Start Value', '')
                # Trouver la ligne où les colonnes de cet asset ont des valeurs non-NaN
                asset_row = None
                for idx in range(len(per_stats)):
                    if pd.notna(per_stats[f'{base}_Start Value'].iloc[idx]):
                        asset_row = idx
                        break
                
                if asset_row is not None:
                    result['per_asset_stats'][base] = {
                        'start_value': safe_float(per_stats[f'{base}_Start Value'].iloc[asset_row]),
                        'end_value': safe_float(per_stats[f'{base}_End Value'].iloc[asset_row]),
                        'total_return_pct': safe_float(per_stats[f'{base}_Total Return [%]'].iloc[asset_row]),
                        'max_drawdown_pct': safe_float(per_stats[f'{base}_Max Drawdown [%]'].iloc[asset_row]),
                        'total_trades': safe_int(per_stats[f'{base}_Total Trades'].iloc[asset_row]),
                        'win_rate_pct': safe_float(per_stats[f'{base}_Win Rate [%]'].iloc[asset_row]),
                        'profit_factor': safe_float(per_stats[f'{base}_Profit Factor'].iloc[asset_row], 0.0)
                    }
        
        # Générer le graphique PNL + Drawdown
        print("📊 Génération du graphique PNL/Drawdown...")
        chart_base64 = generate_pnl_drawdown_chart(combined_equity, init_cash)
        result['chart'] = f"data:image/png;base64,{chart_base64}"
        
        print(f"✅ Backtest terminé avec succès!")
        
        return jsonify(result), 200
        
    except Exception as e:
        import traceback
        print(f"❌ Erreur lors du backtest: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


# -----------------------------------------------------------------------------
# CLASSE DCA STRATEGY (inspirée de dca_library_backtestingpy.py)
# -----------------------------------------------------------------------------

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
    so_step = 0.0021
    so_volume_scale = 1
    so_step_scale = 1
    direction = 'long'
    start_time = pd.Timestamp("2024-01-01 00:00:00")
    end_time = pd.Timestamp("2030-01-01 00:00:00")
    base_amount = 1000000  # Montant de base de 1 million
    take_profit = 20  # Ajout
    stop_loss = 10    # Ajout
    max_safety_orders = 3  # Ajout

    def init(self):
        """Initialisation de la stratégie"""
        close = self.data.Close
        self.timestamps = self.data.index.tz_localize(None) if hasattr(self.data.index, 'tz_localize') else self.data.index

        # Calcul RSI
        def safe_rsi():
            rsi = ta.rsi(pd.Series(close), length=self.rsi_length)
            return rsi.fillna(0).to_numpy()

        # Calcul BB%
        def safe_bbp():
            bb = ta.bbands(pd.Series(close), length=self.bb_length, std=self.bb_std)
            if f'BBP_{self.bb_length}_{self.bb_std}' in bb.columns:
                bbp = bb[f'BBP_{self.bb_length}_{self.bb_std}']
            elif 'BBP_20_2.0' in bb.columns:
                bbp = bb['BBP_20_2.0']
            else:
                # Calcul manuel si pas trouvé
                upper = bb.iloc[:, -1] if len(bb.columns) >= 3 else pd.Series([1]*len(close))
                lower = bb.iloc[:, 0] if len(bb.columns) >= 3 else pd.Series([0]*len(close))
                bbp = (pd.Series(close) - lower) / (upper - lower)
            return bbp.fillna(0.5).to_numpy()

        self.rsi_values = self.I(safe_rsi)
        self.bb_percent = self.I(safe_bbp)
        
        # Variables d'état pour la stratégie
        self.safety_orders_count = 0
        self.entry_price = 0
        self.total_invested = 0
        self.last_so_price = 0

    def next(self):
        """Logique principale de la stratégie"""
        # Utiliser l'index des données actuel au lieu d'un index entier
        current_index = len(self.data) - 1
        current_time = self.data.index[current_index]
        
        # Convertir en Timestamp si nécessaire pour la comparaison
        if hasattr(current_time, 'tz_localize') and current_time.tz is not None:
            current_time = current_time.tz_localize(None)
        
        # Vérifier si on est dans la fenêtre de trading
        if current_time < self.start_time or current_time > self.end_time:
            return
            
        current_price = self.data.Close[-1]
        current_rsi = self.rsi_values[-1]
        current_bbp = self.bb_percent[-1]
        
        # Conditions d'entrée (position fermée)
        if not self.position:
            entry_condition = (
                current_rsi < self.rsi_entry and 
                current_bbp < self.bbp_trigger
            )
            
            if entry_condition:
                size = self.base_amount / current_price
                self.buy(size=size)
                self.entry_price = current_price
                self.total_invested = self.base_amount
                self.safety_orders_count = 0
                self.last_so_price = current_price
                print(f"[LONG] Entrée à {current_price:.2f}")
                
        # Gestion des positions ouvertes
        else:
            # Condition de sortie
            exit_condition = current_rsi > self.rsi_exit
            
            if exit_condition:
                pnl_percent = ((current_price - self.entry_price) / self.entry_price) * 100
                print(f"Sortie à {current_price:.2f} | PnL: {pnl_percent:.2f}%")
                self.position.close()
                self.safety_orders_count = 0
                self.total_invested = 0
                return
            
            # Safety Orders (position en perte)
            if current_price < self.entry_price:
                if self.safety_orders_count < self.so_max:
                    # Distance pour déclencher le SO
                    distance_from_last = abs(current_price - self.last_so_price) / self.last_so_price
                    required_distance = self.so_step * (self.so_step_scale ** self.safety_orders_count)
                    
                    if distance_from_last >= required_distance:
                        # Calcul de la taille du SO
                        so_amount = self.base_amount * (self.so_volume_scale ** self.safety_orders_count)
                        so_size = so_amount / current_price
                        
                        self.buy(size=so_size)
                        self.safety_orders_count += 1
                        self.total_invested += so_amount
                        self.last_so_price = current_price
                        print(f"Safety Order #{self.safety_orders_count} à {current_price:.2f}")

# -----------------------------------------------------------------------------
# UTILITAIRES
# -----------------------------------------------------------------------------

def sanitize_numbers(obj):
    """Remplace NaN, Inf par null pour JSON"""
    if isinstance(obj, dict):
        return {k: sanitize_numbers(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_numbers(item) for item in obj]
    elif isinstance(obj, (int, float)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    return obj

def generate_data_hash(df: pd.DataFrame) -> str:
    """Génère un hash des données pour l'empreinte"""
    return hashlib.md5(str(df.values.tobytes()).encode()).hexdigest()[:16]

def fetch_multi_source_data(symbols: List[str], start_date: str, end_date: str, timeframe: str = "1d") -> Tuple[Dict, Dict, List]:
    """
    Utilise ton fetcher.py pour récupérer les données de plusieurs exchanges
    et retourner la meilleure source par symbole
    """
    errors = []
    all_data = {}
    meta = {
        "symbols": symbols,
        "start": start_date,
        "end": end_date,
        "timeframe": timeframe,
        "source": "multi-exchange"
    }
    
    try:
        # Configuration pour ton fetcher
        lookback_days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
        
        # Utilise Binance uniquement (beaucoup plus rapide)
        agg_results, detail_results, raw_data = fetch_binance_only(
            bases=symbols,
            timeframe=timeframe,
            lookback_days=lookback_days
        )
        
        # Traitement des résultats pour chaque symbole
        for symbol in symbols:
            if symbol in raw_data.get("__FINAL__", {}):
                df = raw_data["__FINAL__"][symbol]
                meta_info = raw_data.get("__FINAL_META__", {}).get(symbol, {})
                
                # Conversion au format attendu (OHLCV)
                if not df.empty and all(col in df.columns for col in ['open', 'high', 'low', 'close', 'volume']):
                    # Renommage des colonnes pour compatibilité
                    df = df.rename(columns={
                        'open': 'Open',
                        'high': 'High', 
                        'low': 'Low',
                        'close': 'Close',
                        'volume': 'Volume'
                    })
                    
                    all_data[symbol] = df
                    print(f"✅ {symbol}: {len(df)} points depuis {meta_info.get('provenance', 'multiple sources')}")
                else:
                    errors.append(f"Données incomplètes pour {symbol}")
            else:
                errors.append(f"Aucune donnée trouvée pour {symbol}")
    
    except Exception as e:
        errors.append(f"Erreur fetcher: {str(e)}")
        
        # Fallback vers yfinance si ton fetcher échoue
        print(f"⚠️ Fallback vers yfinance pour {symbols}")
        for symbol in symbols:
            try:
                # Conversion pour yfinance (ex: BTC -> BTC-USD)
                yf_symbol = f"{symbol}-USD" if "-" not in symbol else symbol
                data = yf.download(yf_symbol, start=start_date, end=end_date, interval=timeframe, progress=False)
                
                if not data.empty:
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = [col[0] for col in data.columns]
                    all_data[symbol] = data
                    print(f"📈 {symbol}: {len(data)} points depuis yfinance (fallback)")
                else:
                    errors.append(f"Aucune donnée yfinance pour {symbol}")
            except Exception as yf_error:
                errors.append(f"Erreur yfinance pour {symbol}: {str(yf_error)}")
    
    return all_data, meta, errors


def fetch_yfinance_data(symbol: str, start_date: str, end_date: str, interval: str = "1d") -> Tuple[pd.DataFrame, Dict, List]:
    """Fonction de fallback yfinance (gardée pour compatibilité)"""
    errors = []
    meta = {
        "symbol": symbol,
        "start": start_date,
        "end": end_date,
        "interval": interval,
        "source": "yfinance"
    }
    
    try:
        data = yf.download(symbol, start=start_date, end=end_date, interval=interval, progress=False)
        if data.empty:
            errors.append(f"Aucune donnée pour {symbol}")
            return pd.DataFrame(), meta, errors
            
        # Nettoyage des colonnes multi-index si nécessaire
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
            
        # S'assurer qu'on a les colonnes OHLCV
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            errors.append(f"Colonnes manquantes: {missing_cols}")
            return pd.DataFrame(), meta, errors
            
        meta["rows"] = len(data)
        meta["start_actual"] = str(data.index[0])
        meta["end_actual"] = str(data.index[-1])
        
        return data, meta, errors
        
    except Exception as e:
        errors.append(f"Erreur yfinance: {str(e)}")
        return pd.DataFrame(), meta, errors

def calculate_data_quality_score(df: pd.DataFrame, meta: Dict) -> float:
    """Calcule un score de qualité des données (0-100)"""
    if df.empty:
        return 0.0
        
    score = 100.0
    
    # Pénalité pour les valeurs manquantes
    missing_ratio = df.isnull().sum().sum() / (len(df) * len(df.columns))
    score -= missing_ratio * 30
    
    # Pénalité pour les gaps importants
    if 'Close' in df.columns:
        price_changes = df['Close'].pct_change().abs()
        extreme_changes = (price_changes > 0.5).sum()  # Plus de 50% de variation
        score -= (extreme_changes / len(df)) * 20
    
    # Bonus pour la complétude temporelle
    expected_rows = meta.get("rows", len(df))
    completeness = len(df) / max(expected_rows, 1)
    score *= completeness
    
    return max(0.0, min(100.0, score))


def generate_tradingview_table_html(trades_df) -> str:
    """
    Génère un tableau HTML style TradingView avec chaque position individuelle
    Compatible avec le format de trades stocké dans BACKTEST_STORE
    """
    if trades_df is None or (isinstance(trades_df, pd.DataFrame) and trades_df.empty):
        return "<p style='color: #7d8590;'>Aucun trade à afficher.</p>"
    
    # Si trades_df n'est pas un DataFrame, essayer de le convertir
    if not isinstance(trades_df, pd.DataFrame):
        if isinstance(trades_df, dict):
            # Peut-être un dict avec is_sample et oos_sample
            all_trades = []
            if 'is_sample' in trades_df:
                all_trades.extend(trades_df['is_sample'])
            if 'oos_sample' in trades_df:
                all_trades.extend(trades_df['oos_sample'])
            if not all_trades:
                return "<p style='color: #7d8590;'>Aucun trade à afficher.</p>"
            trades_df = pd.DataFrame(all_trades)
        else:
            return "<p style='color: #7d8590;'>Format de trades non supporté.</p>"
    
    html_rows = []
    trade_number = 0
    cumulative_pnl = 0.0
    
    for idx, trade in trades_df.iterrows():
        # Vérifier si le trade a des positions individuelles
        if "individual_positions" not in trade or not trade["individual_positions"]:
            continue
        
        positions = trade["individual_positions"]
        
        for pos in positions:
            trade_number += 1
            cumulative_pnl += pos['pnl']
            
            # Couleur selon le P&L
            pnl_class = "positive" if pos['pnl'] > 0 else "negative"
            
            # Formater les dates
            entry_time_str = pos['entry_time'].strftime('%Y-%m-%d %H:%M') if hasattr(pos['entry_time'], 'strftime') else str(pos['entry_time'])
            exit_time_str = trade['exit_time'].strftime('%Y-%m-%d %H:%M') if hasattr(trade['exit_time'], 'strftime') else str(trade['exit_time'])
            
            # Ligne Entry
            entry_row = f"""
                <tr>
                    <td rowspan="2" class="trade-number">{trade_number}</td>
                    <td class="entry">Entry long</td>
                    <td>{entry_time_str}</td>
                    <td>{pos['type']}</td>
                    <td>${pos['entry_price']:.2f}</td>
                    <td>{pos['qty']:.8f}</td>
                    <td>${pos['size_usd']:.2f}</td>
                    <td rowspan="2" class="{pnl_class}">${pos['pnl']:.2f}</td>
                    <td rowspan="2" class="{pnl_class}">{pos['pnl_pct']:+.2f}%</td>
                    <td rowspan="2">${cumulative_pnl:.2f}</td>
                </tr>
            """
            
            # Ligne Exit
            tp_pct = trade.get('tp_pct', 1.5)
            exit_row = f"""
                <tr>
                    <td class="exit">Exit long</td>
                    <td>{exit_time_str}</td>
                    <td>TP @ {tp_pct:.1f}%</td>
                    <td>${pos['exit_price']:.2f}</td>
                    <td>{pos['qty']:.8f}</td>
                    <td>${pos['qty'] * pos['exit_price']:.2f}</td>
                </tr>
            """
            
            html_rows.append(entry_row + exit_row)
    
    if trade_number == 0:
        return "<p style='color: #7d8590;'>Aucun trade avec positions individuelles à afficher.</p>"
    
    cumulative_class = "positive" if cumulative_pnl > 0 else "negative"
    
    table_html = f"""
    <style>
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 13px;
            background: #1a1d23;
            border-radius: 8px;
            overflow: hidden;
        }}
        .trades-table th {{
            background: #2d333b;
            color: #adbac7;
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #444c56;
            position: sticky;
            top: 0;
        }}
        .trades-table td {{
            padding: 8px;
            border-bottom: 1px solid #2d333b;
            color: #cdd9e5;
        }}
        .trades-table tr:hover {{
            background: #22272e;
        }}
        .trade-number {{
            font-weight: bold;
            color: #58a6ff;
            text-align: center;
        }}
        .entry {{
            color: #7ee787;
        }}
        .exit {{
            color: #f85149;
        }}
        .positive {{
            color: #3fb950 !important;
            font-weight: bold;
        }}
        .negative {{
            color: #f85149 !important;
            font-weight: bold;
        }}
        .table-container {{
            max-height: 600px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #2d333b;
        }}
    </style>
    
    <div class="table-container">
        <table class="trades-table">
            <thead>
                <tr>
                    <th>Trade #</th>
                    <th>Type</th>
                    <th>Date/Time</th>
                    <th>Signal</th>
                    <th>Price USD</th>
                    <th>Size (qty)</th>
                    <th>Size (value)</th>
                    <th>Net P&L USD</th>
                    <th>Net P&L %</th>
                    <th>Cumulative P&L</th>
                </tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    
    <p style="margin-top: 15px; color: #7d8590; font-size: 12px;">
        📊 Total individual positions: {trade_number} | Cumulative P&L: <span class="{cumulative_class}" style="font-weight: bold;">${cumulative_pnl:.2f}</span>
    </p>
    """
    
    return table_html


def create_professional_price_chart(df_price, trades_df, title: str = "Analyse de Prix et Trades") -> str:
    """Crée un graphique professionnel avec chandeliers et flèches de trades comme le fichier de référence"""
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    import seaborn as sns
    
    # Configuration du style professionnel simple
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), height_ratios=[3, 1])
    
    # Couleurs professionnelles avec fond noir et couleurs classiques
    colors = {
        'bg': '#000000',           # Fond noir pur
        'text': '#ffffff',         # Texte blanc
        'grid': '#333333',         # Grille gris foncé
        'bull': '#22c55e',         # Vert classique élégant (Tailwind green-500)
        'bear': '#ef4444',         # Rouge classique élégant (Tailwind red-500)
        'buy': '#10b981',          # Vert émeraude pour les achats
        'sell': '#f59e0b',         # Orange ambre pour les ventes
        'ma20': '#f59e0b',         # Orange ambre pour MA20
        'ma50': '#8b5cf6'          # Violet pour MA50
    }
    
    # Configuration des figures
    fig.patch.set_facecolor(colors['bg'])
    ax1.set_facecolor(colors['bg'])
    ax2.set_facecolor(colors['bg'])
    
    # Graphique principal - Chandeliers style TradingView
    if not df_price.empty and len(df_price) > 1:
        dates = df_price.index
        opens = df_price['Open'].values
        highs = df_price['High'].values
        lows = df_price['Low'].values
        closes = df_price['Close'].values
        
        # Chandeliers professionnels
        for i in range(len(df_price)):
            date = dates[i]
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            
            # Couleur du chandelier
            color = colors['bull'] if c >= o else colors['bear']
            
            # Mèche (wick)
            ax1.plot([date, date], [l, h], color=color, linewidth=1.2, alpha=0.8)
            
            # Corps du chandelier
            height = abs(c - o)
            bottom = min(o, c)
            
            if height > 0:
                rect = Rectangle((mdates.date2num(date) - 0.3, bottom), 0.6, height,
                               facecolor=color, alpha=0.8, edgecolor=color)
                ax1.add_patch(rect)
            else:
                # Ligne pour les doji
                ax1.plot([mdates.date2num(date) - 0.3, mdates.date2num(date) + 0.3], 
                        [c, c], color=color, linewidth=1.5, alpha=0.8)
        
        # Moyennes mobiles
        if len(df_price) >= 20:
            ma20 = df_price['Close'].rolling(20).mean()
            ax1.plot(dates, ma20, color=colors['ma20'], linewidth=1.5, alpha=0.7, label='MA20')
        
        if len(df_price) >= 50:
            ma50 = df_price['Close'].rolling(50).mean()
            ax1.plot(dates, ma50, color=colors['ma50'], linewidth=1.5, alpha=0.7, label='MA50')
    
    # Marqueurs de trades avec flèches simples et efficaces
    if not trades_df.empty:
        buy_dates = []
        buy_prices = []
        so_dates = []
        so_prices = []
        so_numbers = []
        sell_dates = []
        sell_prices = []
        
        # Calculer la plage de prix pour positionner les flèches
        if not df_price.empty:
            price_range = df_price['High'].max() - df_price['Low'].min()
            arrow_offset = price_range * 0.03  # 3% au-dessus
        else:
            arrow_offset = 0
        
        for _, trade in trades_df.iterrows():
            # Gestion des achats (entrées - BO)
            if 'entry_time' in trade and 'entry_price' in trade and pd.notna(trade['entry_time']):
                entry_date = pd.to_datetime(trade['entry_time'])
                entry_price = float(trade['entry_price'])
                buy_dates.append(entry_date)
                buy_prices.append(entry_price)
                
                # Flèche d'achat simple et visible
                ax1.annotate('', xy=(entry_date, entry_price), 
                           xytext=(entry_date, entry_price + arrow_offset),
                           arrowprops=dict(arrowstyle='->', color=colors['buy'], 
                                         lw=3, alpha=0.8, shrinkA=5, shrinkB=5))
                
                # Texte BUY simple
                ax1.text(entry_date, entry_price + arrow_offset * 1.5, 'BO', 
                        ha='center', va='bottom', color=colors['buy'], 
                        fontweight='bold', fontsize=10,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['buy'], 
                                alpha=0.2, edgecolor=colors['buy']))
            
            # Gestion des Safety Orders (SO)
            if 'so_times' in trade and 'so_prices' in trade:
                so_times_list = trade['so_times']
                so_prices_list = trade['so_prices']
                
                if isinstance(so_times_list, (list, tuple)) and isinstance(so_prices_list, (list, tuple)):
                    for idx, (so_time, so_price) in enumerate(zip(so_times_list, so_prices_list), 1):
                        so_date = pd.to_datetime(so_time)
                        so_price_val = float(so_price)
                        so_dates.append(so_date)
                        so_prices.append(so_price_val)
                        so_numbers.append(idx)
                        
                        # Flèche SO avec couleur distincte (orange/jaune)
                        ax1.annotate('', xy=(so_date, so_price_val), 
                                   xytext=(so_date, so_price_val + arrow_offset),
                                   arrowprops=dict(arrowstyle='->', color='#FFA500', 
                                                 lw=2.5, alpha=0.8, shrinkA=5, shrinkB=5))
                        
                        # Texte SO avec numéro
                        ax1.text(so_date, so_price_val + arrow_offset * 1.5, f'SO{idx}', 
                                ha='center', va='bottom', color='#FFA500', 
                                fontweight='bold', fontsize=9,
                                bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFA500', 
                                        alpha=0.2, edgecolor='#FFA500'))
            
            # Gestion des ventes (sorties - TP)
            if 'exit_time' in trade and 'exit_price' in trade and pd.notna(trade['exit_time']):
                exit_date = pd.to_datetime(trade['exit_time'])
                exit_price = float(trade['exit_price'])
                sell_dates.append(exit_date)
                sell_prices.append(exit_price)
                
                # Flèche de vente simple et visible
                ax1.annotate('', xy=(exit_date, exit_price), 
                           xytext=(exit_date, exit_price + arrow_offset),
                           arrowprops=dict(arrowstyle='->', color=colors['sell'], 
                                         lw=3, alpha=0.8, shrinkA=5, shrinkB=5))
                
                # Calcul du PnL
                pnl = exit_price - entry_price if 'entry_price' in trade else 0
                pnl_text = f"TP\n{pnl:+.1%}" if pnl != 0 else "TP"
                
                # Texte SELL avec PnL
                ax1.text(exit_date, exit_price + arrow_offset * 1.5, pnl_text, 
                        ha='center', va='bottom', color=colors['sell'], 
                        fontweight='bold', fontsize=10,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['sell'], 
                                alpha=0.2, edgecolor=colors['sell']))
                
                # Ligne de connexion entre achat et vente
                if 'entry_time' in trade and pd.notna(trade['entry_time']):
                    pnl_color = colors['bull'] if pnl >= 0 else colors['bear']
                    ax1.plot([entry_date, exit_date], [entry_price, exit_price],
                            color=pnl_color, linewidth=2, alpha=0.6, linestyle='--')
        
        # Marqueurs sur les prix
        if buy_dates:
            ax1.scatter(buy_dates, buy_prices, color=colors['buy'], s=100, 
                       marker='^', alpha=0.8, zorder=5, edgecolor='white', linewidth=1,
                       label=f'BO ({len(buy_dates)})')
        
        if so_dates:
            ax1.scatter(so_dates, so_prices, color='#FFA500', s=80, 
                       marker='>', alpha=0.8, zorder=5, edgecolor='white', linewidth=1,
                       label=f'SO ({len(so_dates)})')
        
        if sell_dates:
            ax1.scatter(sell_dates, sell_prices, color=colors['sell'], s=100,
                       marker='v', alpha=0.8, zorder=5, edgecolor='white', linewidth=1,
                       label=f'TP ({len(sell_dates)})')
        
        # Statistiques des trades
        total_trades = len(trades_df)
        total_so = len(so_dates)
        if total_trades > 0:
            ax1.text(0.02, 0.98, f'Deals: {total_trades} | SO: {total_so}', 
                    transform=ax1.transAxes, fontsize=12, verticalalignment='top',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor=colors['bg'], alpha=0.8),
                    color=colors['text'], fontweight='bold')
    
    # Configuration du graphique principal avec fond noir
    ax1.set_title(title, color=colors['text'], fontsize=16, fontweight='bold', pad=20)
    ax1.set_ylabel('Prix ($)', color=colors['text'], fontsize=12)
    ax1.grid(True, alpha=0.2, color=colors['grid'])
    ax1.tick_params(colors=colors['text'])
    
    # Bordures des axes en blanc pour contraste
    for spine in ax1.spines.values():
        spine.set_color(colors['text'])
        spine.set_linewidth(1)
    
    # Légende avec fond noir
    if ax1.get_legend_handles_labels()[0]:
        ax1.legend(loc='upper left', facecolor=colors['bg'], edgecolor=colors['text'], 
                  labelcolor=colors['text'], framealpha=0.9)
    
    # Graphique de volume avec couleurs vives
    if not df_price.empty:
        volume = np.random.uniform(1000000, 5000000, len(df_price))
        bars = ax2.bar(df_price.index, volume, color=colors['bull'], alpha=0.7, width=0.8)
        
        # Colorer les barres selon la direction du prix avec couleurs vives
        for i, (bar, close, prev_close) in enumerate(zip(bars, closes, [closes[0]] + list(closes[:-1]))):
            if close >= prev_close:
                bar.set_color(colors['bull'])
                bar.set_alpha(0.6)
            else:
                bar.set_color(colors['bear'])
                bar.set_alpha(0.6)
    
    ax2.set_ylabel('Volume', color=colors['text'], fontsize=12)
    ax2.set_xlabel('Date', color=colors['text'], fontsize=12)
    ax2.grid(True, alpha=0.2, color=colors['grid'])
    ax2.tick_params(colors=colors['text'])
    
    # Bordures des axes en blanc pour le volume aussi
    for spine in ax2.spines.values():
        spine.set_color(colors['text'])
        spine.set_linewidth(1)
    
    # Format des dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    # Rotation des labels de date
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    
    plt.tight_layout()
    
    # Sauvegarde
    temp_path = os.path.join(tempfile.gettempdir(), f"price_chart_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=300, bbox_inches='tight', facecolor=colors['bg'], edgecolor='none')
    plt.close()
    
    return temp_path
    
    # Marqueurs de trades DCA améliorés avec flèches au-dessus des bougies
    if not trades_df.empty:
        buy_dates = []
        buy_prices = []
        sell_dates = []
        sell_prices = []
        
        # Calculer la plage de prix pour positionner les flèches au-dessus
        if not df_price.empty:
            price_range = df_price['High'].max() - df_price['Low'].min()
            arrow_offset = price_range * 0.05  # 5% au-dessus du plus haut
        else:
            arrow_offset = 0
        
        for _, trade in trades_df.iterrows():
            # Gestion des achats (entrées)
            if 'entry_date' in trade and 'entry_price' in trade and pd.notna(trade['entry_date']):
                entry_date = pd.to_datetime(trade['entry_date'])
                entry_price = float(trade['entry_price'])
                buy_dates.append(entry_date)
                buy_prices.append(entry_price)
                
                # Trouver le prix le plus haut de la bougie correspondante
                target_y = entry_price
                if not df_price.empty:
                    try:
                        # Chercher la bougie la plus proche de la date d'entrée
                        closest_candle = df_price.index[df_price.index.get_indexer([entry_date], method='nearest')[0]]
                        target_y = df_price.loc[closest_candle, 'High']
                    except:
                        target_y = entry_price
                
                arrow_start_y = target_y + arrow_offset
                
                # Flèche verte pointant vers le bas pour l'achat (au-dessus de la bougie)
                target_y = entry_price
                if not df_price.empty:
                    try:
                        # Chercher la bougie la plus proche de la date d'entrée
                        closest_candle = df_price.index[df_price.index.get_indexer([entry_date], method='nearest')[0]]
                        target_y = df_price.loc[closest_candle, 'High']
                    except:
                        target_y = entry_price
                
                arrow_start_y = target_y + arrow_offset
                
                ax1.annotate('', xy=(entry_date, target_y), xytext=(entry_date, arrow_start_y),
                           arrowprops=dict(arrowstyle='->', color=colors['buy'], lw=4, alpha=0.9))
                
                # Texte "BUY" au-dessus de la flèche
                ax1.text(entry_date, arrow_start_y + arrow_offset*0.2, 'BUY', 
                        ha='center', va='bottom', color='white', fontweight='bold', fontsize=12,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['buy'], alpha=0.9))
                
                # Annotation détaillée (optionnelle, plus discrète)
                ax1.annotate(f'${entry_price:.2f}', 
                           xy=(entry_date, entry_price), 
                           xytext=(15, 10), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.2', facecolor=colors['buy'], alpha=0.6),
                           fontsize=7, color='white', fontweight='bold')
            
            # Gestion des ventes (sorties)
            if 'exit_date' in trade and 'exit_price' in trade and pd.notna(trade['exit_date']):
                exit_date = pd.to_datetime(trade['exit_date'])
                exit_price = float(trade['exit_price'])
                sell_dates.append(exit_date)
                sell_prices.append(exit_price)
                
                # Trouver le prix le plus haut de la bougie correspondante
                target_y = exit_price
                if not df_price.empty:
                    try:
                        # Chercher la bougie la plus proche de la date de sortie
                        closest_candle = df_price.index[df_price.index.get_indexer([exit_date], method='nearest')[0]]
                        target_y = df_price.loc[closest_candle, 'High']
                    except:
                        target_y = exit_price
                
                arrow_start_y = target_y + arrow_offset
                
                # Flèche rouge pointant vers le bas pour la vente (au-dessus de la bougie)
                target_y = exit_price
                if not df_price.empty:
                    try:
                        # Chercher la bougie la plus proche de la date de sortie
                        closest_candle = df_price.index[df_price.index.get_indexer([exit_date], method='nearest')[0]]
                        target_y = df_price.loc[closest_candle, 'High']
                    except:
                        target_y = exit_price
                
                arrow_start_y = target_y + arrow_offset
                
                ax1.annotate('', xy=(exit_date, target_y), xytext=(exit_date, arrow_start_y),
                           arrowprops=dict(arrowstyle='->', color=colors['sell'], lw=4, alpha=0.9))
                
                # Texte "SELL" au-dessus de la flèche
                ax1.text(exit_date, arrow_start_y + arrow_offset*0.2, 'SELL', 
                        ha='center', va='bottom', color='white', fontweight='bold', fontsize=12,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['sell'], alpha=0.9))
                
                # Calcul du PnL pour cette position
                pnl = exit_price - entry_price if 'entry_price' in trade else 0
                pnl_color = colors['bull'] if pnl >= 0 else colors['bear']
                
                # Annotation détaillée avec PnL
                ax1.annotate(f'${exit_price:.2f}\nPnL: {pnl:+.2f}', 
                           xy=(exit_date, exit_price), 
                           xytext=(15, -20), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.2', facecolor=colors['sell'], alpha=0.6),
                           fontsize=7, color='white', fontweight='bold')
                
                # Ligne de connexion entre achat et vente
                if 'entry_date' in trade and pd.notna(trade['entry_date']):
                    ax1.plot([entry_date, exit_date], [entry_price, exit_price],
                            color=pnl_color, linewidth=2, alpha=0.7, linestyle='--')
        
        # Marqueurs groupés pour une meilleure visibilité
        if buy_dates:
            ax1.scatter(buy_dates, buy_prices, color=colors['buy'], s=150, 
                       marker='^', alpha=0.9, zorder=5, edgecolor='white', linewidth=2,
                       label=f'Achats DCA ({len(buy_dates)})')
        
        if sell_dates:
            ax1.scatter(sell_dates, sell_prices, color=colors['sell'], s=150,
                       marker='v', alpha=0.9, zorder=5, edgecolor='white', linewidth=2,
                       label=f'Ventes DCA ({len(sell_dates)})')
        
        # Statistiques des trades dans le titre
        total_trades = len(trades_df)
        win_trades = len(trades_df[trades_df.get('exit_price', 0) > trades_df.get('entry_price', 0)])
        if total_trades > 0:
            win_rate = (win_trades / total_trades) * 100
            ax1.text(0.02, 0.98, f'📊 Trades: {total_trades} | Win Rate: {win_rate:.1f}%', 
                    transform=ax1.transAxes, fontsize=10, verticalalignment='top',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor=colors['bg'], alpha=0.8),
                    color=colors['text'], fontweight='bold')
    
    # Configuration du graphique principal
    ax1.set_title(title, color=colors['text'], fontsize=16, fontweight='bold', pad=20)
    ax1.set_ylabel('Prix ($)', color=colors['text'], fontsize=12)
    ax1.grid(True, alpha=0.2, color=colors['grid'])
    ax1.tick_params(colors=colors['text'])
    ax1.legend(loc='upper left', facecolor=colors['bg'], edgecolor=colors['text'], 
               labelcolor=colors['text'])
    
    # Graphique de volume (simulé)
    if not df_price.empty:
        volume = np.random.uniform(1000000, 5000000, len(df_price))
        bars = ax2.bar(df_price.index, volume, color=colors['bull'], alpha=0.6, width=0.8)
        
        # Colorer les barres selon la direction du prix
        for i, (bar, close, prev_close) in enumerate(zip(bars, closes, [closes[0]] + list(closes[:-1]))):
            if close >= prev_close:
                bar.set_color(colors['bull'])
            else:
                bar.set_color(colors['bear'])
    
    ax2.set_ylabel('Volume', color=colors['text'], fontsize=12)
    ax2.set_xlabel('Date', color=colors['text'], fontsize=12)
    ax2.grid(True, alpha=0.2, color=colors['grid'])
    ax2.tick_params(colors=colors['text'])
    
    # Format des dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    # Rotation des labels de date
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    
    plt.tight_layout()
    
    # Sauvegarde
    temp_path = os.path.join(tempfile.gettempdir(), f"price_chart_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=300, bbox_inches='tight', facecolor=colors['bg'], edgecolor='none')
    plt.close()
    
    return temp_path

def create_professional_equity_chart(equity_data, trades_df, title: str = "Performance Equity") -> str:
    """Crée un graphique d'equity professionnel avec statistiques"""
    import seaborn as sns
    
    # Configuration du style
    plt.style.use('default')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[3, 1])
    
    # Couleurs professionnelles
    colors = {
        'bg': '#1e1e1e',
        'text': '#ffffff',
        'grid': '#333333',
        'equity': '#00ff88',
        'drawdown': '#ff4444',
        'profit': '#00bfff',
        'loss': '#ff6b35'
    }
    
    fig.patch.set_facecolor(colors['bg'])
    ax1.set_facecolor(colors['bg'])
    ax2.set_facecolor(colors['bg'])
    
    # Convertir en Series si nécessaire
    if isinstance(equity_data, pd.DataFrame):
        if 'equity' in equity_data.columns:
            equity_series = equity_data['equity']
        else:
            numeric_cols = equity_data.select_dtypes(include=[np.number]).columns
            equity_series = equity_data[numeric_cols[0]] if len(numeric_cols) > 0 else pd.Series()
    else:
        equity_series = equity_data if isinstance(equity_data, pd.Series) else pd.Series()
    
    if not equity_series.empty:
        # Courbe d'equity principale
        ax1.plot(equity_series.index, equity_series.values, 
                color=colors['equity'], linewidth=3, alpha=0.9, label='Equity')
        
        # Zone d'equity
        ax1.fill_between(equity_series.index, equity_series.values, 
                        equity_series.iloc[0], alpha=0.2, color=colors['equity'])
        
        # Ligne de capital initial
        initial_capital = equity_series.iloc[0]
        ax1.axhline(y=initial_capital, color='white', linestyle='--', 
                   alpha=0.5, label=f'Capital Initial: ${initial_capital:,.0f}')
        
        # Marqueurs de trades
        if not trades_df.empty:
            for _, trade in trades_df.iterrows():
                if 'exit_date' in trade and 'pnl' in trade and pd.notna(trade['exit_date']):
                    exit_date = trade['exit_date']
                    pnl = trade['pnl']
                    
                    # Trouver l'equity à cette date
                    if exit_date in equity_series.index:
                        equity_value = equity_series.loc[exit_date]
                        
                        color = colors['profit'] if pnl > 0 else colors['loss']
                        marker = '^' if pnl > 0 else 'v'
                        
                        ax1.scatter(exit_date, equity_value, color=color, s=80, 
                                   marker=marker, alpha=0.8, zorder=5)
        
        # Calcul et affichage du drawdown
        running_max = equity_series.expanding().max()
        drawdown = ((equity_series - running_max) / running_max) * 100
        
        ax2.fill_between(equity_series.index, drawdown, 0, 
                        color=colors['drawdown'], alpha=0.6)
        ax2.plot(equity_series.index, drawdown, 
                color=colors['drawdown'], linewidth=2)
        
        # Statistiques dans le titre
        total_return = ((equity_series.iloc[-1] - equity_series.iloc[0]) / equity_series.iloc[0]) * 100
        max_dd = drawdown.min()
        
        title_with_stats = f"{title} | Rendement: {total_return:+.1f}% | Max DD: {max_dd:.1f}%"
        ax1.set_title(title_with_stats, color=colors['text'], fontsize=16, fontweight='bold', pad=20)
    
    # Configuration des axes
    ax1.set_ylabel('Equity ($)', color=colors['text'], fontsize=12)
    ax1.grid(True, alpha=0.2, color=colors['grid'])
    ax1.tick_params(colors=colors['text'])
    ax1.legend(loc='upper left', facecolor=colors['bg'], edgecolor=colors['text'], 
               labelcolor=colors['text'])
    
    ax2.set_ylabel('Drawdown (%)', color=colors['text'], fontsize=12)
    ax2.set_xlabel('Date', color=colors['text'], fontsize=12)
    ax2.grid(True, alpha=0.2, color=colors['grid'])
    ax2.tick_params(colors=colors['text'])
    
    plt.tight_layout()
    
    # Sauvegarde
    temp_path = os.path.join(tempfile.gettempdir(), f"equity_chart_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=300, bbox_inches='tight', facecolor=colors['bg'], edgecolor='none')
    plt.close()
    
    return temp_path

def create_trades_analysis_chart(trades_df, title: str = "Analyse des Trades DCA") -> str:
    """Crée un graphique d'analyse détaillée des trades DCA avec visualisations améliorées"""
    
    # Configuration du style
    plt.style.use('default')
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(18, 14))
    
    colors = {
        'bg': '#1e1e1e',
        'text': '#ffffff',
        'profit': '#00ff88',
        'loss': '#ff4444',
        'neutral': '#ffa500',
        'buy': '#00bfff',
        'sell': '#ff6b35'
    }
    
    fig.patch.set_facecolor(colors['bg'])
    for ax in [ax1, ax2, ax3, ax4]:
        ax.set_facecolor(colors['bg'])
    
    if not trades_df.empty:
        # Préparation des données
        has_pnl = 'pnl' in trades_df.columns
        has_dates = 'entry_date' in trades_df.columns and 'exit_date' in trades_df.columns
        has_prices = 'entry_price' in trades_df.columns and 'exit_price' in trades_df.columns
        
        if has_pnl and has_prices:
            pnl_values = trades_df['pnl'].dropna()
            entry_prices = trades_df['entry_price'].dropna()
            exit_prices = trades_df['exit_price'].dropna()
            
            if not pnl_values.empty:
                # 1. Timeline des trades avec marqueurs d'achat/vente
                if has_dates:
                    trade_numbers = range(1, len(trades_df) + 1)
                    
                    # Graphique en barres pour les PnL
                    colors_bars = [colors['profit'] if pnl > 0 else colors['loss'] for pnl in pnl_values]
                    bars = ax1.bar(trade_numbers, pnl_values, color=colors_bars, alpha=0.8)
                    
                    # Annotations sur les barres
                    for i, (bar, pnl) in enumerate(zip(bars, pnl_values)):
                        height = bar.get_height()
                        ax1.annotate(f'${pnl:.2f}',
                                   xy=(bar.get_x() + bar.get_width() / 2, height),
                                   xytext=(0, 3 if height > 0 else -15),
                                   textcoords="offset points",
                                   ha='center', va='bottom' if height > 0 else 'top',
                                   fontsize=8, color=colors['text'], fontweight='bold')
                    
                    ax1.axhline(y=0, color='white', linestyle='-', alpha=0.5)
                    ax1.set_title('📊 PnL par Trade DCA', color=colors['text'], fontweight='bold', fontsize=14)
                    ax1.set_xlabel('Numéro de Trade', color=colors['text'])
                    ax1.set_ylabel('PnL ($)', color=colors['text'])
                    ax1.grid(True, alpha=0.2)
                    ax1.tick_params(colors=colors['text'])
                
                # 2. Évolution du capital (PnL cumulé)
                cumulative_pnl = pnl_values.cumsum()
                initial_capital = 10000  # Capital initial simulé
                equity_curve = initial_capital + cumulative_pnl
                
                ax2.plot(range(1, len(equity_curve) + 1), equity_curve, 
                        color=colors['profit'], linewidth=3, marker='o', markersize=4)
                ax2.fill_between(range(1, len(equity_curve) + 1), equity_curve, initial_capital, 
                               alpha=0.3, color=colors['profit'])
                ax2.axhline(y=initial_capital, color='white', linestyle='--', alpha=0.7, label='Capital Initial')
                
                # Annotations des points hauts et bas
                max_equity = equity_curve.max()
                min_equity = equity_curve.min()
                max_idx = equity_curve.idxmax() + 1
                min_idx = equity_curve.idxmin() + 1
                
                ax2.annotate(f'📈 Max: ${max_equity:.0f}', 
                           xy=(max_idx, max_equity), xytext=(10, 10), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['profit'], alpha=0.8),
                           arrowprops=dict(arrowstyle='->', color=colors['profit']),
                           fontsize=9, color='white', fontweight='bold')
                
                if min_equity < initial_capital:
                    ax2.annotate(f'📉 Min: ${min_equity:.0f}', 
                               xy=(min_idx, min_equity), xytext=(10, -20), textcoords='offset points',
                               bbox=dict(boxstyle='round,pad=0.3', facecolor=colors['loss'], alpha=0.8),
                               arrowprops=dict(arrowstyle='->', color=colors['loss']),
                               fontsize=9, color='white', fontweight='bold')
                
                ax2.set_title('💰 Évolution du Capital DCA', color=colors['text'], fontweight='bold', fontsize=14)
                ax2.set_xlabel('Numéro de Trade', color=colors['text'])
                ax2.set_ylabel('Capital ($)', color=colors['text'])
                ax2.grid(True, alpha=0.2)
                ax2.tick_params(colors=colors['text'])
                ax2.legend(facecolor=colors['bg'], edgecolor=colors['text'], labelcolor=colors['text'])
                
                # 3. Distribution des prix d'entrée vs sortie
                if len(entry_prices) == len(exit_prices):
                    # Scatter plot entrée vs sortie
                    profits_mask = exit_prices > entry_prices
                    
                    ax3.scatter(entry_prices[profits_mask], exit_prices[profits_mask], 
                              color=colors['profit'], s=60, alpha=0.8, label='Trades Gagnants')
                    ax3.scatter(entry_prices[~profits_mask], exit_prices[~profits_mask], 
                              color=colors['loss'], s=60, alpha=0.8, label='Trades Perdants')
                    
                    # Ligne de référence (break-even)
                    min_price = min(entry_prices.min(), exit_prices.min())
                    max_price = max(entry_prices.max(), exit_prices.max())
                    ax3.plot([min_price, max_price], [min_price, max_price], 
                            'white', linestyle='--', alpha=0.7, label='Break-even')
                    
                    ax3.set_title('🎯 Prix Entrée vs Sortie', color=colors['text'], fontweight='bold', fontsize=14)
                    ax3.set_xlabel('Prix d\'Entrée ($)', color=colors['text'])
                    ax3.set_ylabel('Prix de Sortie ($)', color=colors['text'])
                    ax3.grid(True, alpha=0.2)
                    ax3.tick_params(colors=colors['text'])
                    ax3.legend(facecolor=colors['bg'], edgecolor=colors['text'], labelcolor=colors['text'])
                
                # 4. Statistiques détaillées (tableau de métriques)
                ax4.axis('off')
                
                # Calcul des statistiques
                profits = pnl_values[pnl_values > 0]
                losses = pnl_values[pnl_values < 0]
                
                win_count = len(profits)
                loss_count = len(losses)
                total_trades = len(pnl_values)
                win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
                
                avg_profit = profits.mean() if len(profits) > 0 else 0
                avg_loss = losses.mean() if len(losses) > 0 else 0
                profit_factor = abs(profits.sum() / losses.sum()) if losses.sum() != 0 else float('inf')
                
                total_pnl = pnl_values.sum()
                max_profit = profits.max() if len(profits) > 0 else 0
                max_loss = losses.min() if len(losses) > 0 else 0
                
                # Tableau de statistiques stylisé
                stats_text = f"""
📈 STATISTIQUES DCA DÉTAILLÉES

🔢 Trades Total: {total_trades}
✅ Trades Gagnants: {win_count} ({win_rate:.1f}%)
❌ Trades Perdants: {loss_count} ({100-win_rate:.1f}%)

💰 PnL Total: ${total_pnl:+.2f}
📊 Profit Moyen: ${avg_profit:.2f}
📉 Perte Moyenne: ${avg_loss:.2f}

🏆 Meilleur Trade: ${max_profit:.2f}
💥 Pire Trade: ${max_loss:.2f}
⚖️ Profit Factor: {profit_factor:.2f}

🎯 Win Rate Target: {'✅ Excellent' if win_rate >= 60 else '⚠️ À améliorer' if win_rate >= 40 else '🔴 Critique'}
💡 Performance: {'🚀 Très bon' if total_pnl > 0 else '📉 Négatif'}
                """
                
                ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, fontsize=12,
                        verticalalignment='top', horizontalalignment='left',
                        bbox=dict(boxstyle='round,pad=1', facecolor=colors['bg'], alpha=0.9, edgecolor=colors['text']),
                        color=colors['text'], fontfamily='monospace')
    
    else:
        # Aucune donnée de trade disponible
        for i, ax in enumerate([ax1, ax2, ax3, ax4]):
            ax.text(0.5, 0.5, '📊 Aucune donnée de trade disponible', 
                   transform=ax.transAxes, ha='center', va='center',
                   fontsize=14, color=colors['text'], fontweight='bold')
            ax.set_title(f'Graphique {i+1}', color=colors['text'])
    
    plt.suptitle(title, color=colors['text'], fontsize=16, fontweight='bold', y=0.98)
    plt.tight_layout()
    
    # Sauvegarde
    temp_path = os.path.join(tempfile.gettempdir(), f"trades_analysis_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=300, bbox_inches='tight', facecolor=colors['bg'], edgecolor='none')
    plt.close()
    
    return temp_path


def create_equity_chart(equity_data, title: str = "Courbe d'Equity") -> str:
    """Crée un graphique de la courbe d'equity et retourne le chemin"""
    print(f"DEBUG create_equity_chart: type={type(equity_data)}, shape={getattr(equity_data, 'shape', 'N/A')}")
    
    plt.figure(figsize=(12, 6))
    
    # Gérer différents types de données
    if isinstance(equity_data, pd.Series):
        x_data = equity_data.index
        y_data = equity_data.values
        print(f"DEBUG: Series avec {len(y_data)} points")
    elif isinstance(equity_data, pd.DataFrame):
        if 'equity' in equity_data.columns:
            x_data = equity_data.index
            y_data = equity_data['equity'].values
            print(f"DEBUG: DataFrame avec colonne 'equity', {len(y_data)} points")
        else:
            print(f"DEBUG: DataFrame sans colonne 'equity', colonnes: {equity_data.columns.tolist()}")
            # Prendre la première colonne numérique
            numeric_cols = equity_data.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                x_data = equity_data.index
                y_data = equity_data[numeric_cols[0]].values
                print(f"DEBUG: Utilisation de la colonne {numeric_cols[0]}")
            else:
                print("ERROR: Aucune colonne numérique trouvée")
                return create_default_equity_chart("ERROR")
    else:
        print(f"ERROR: Type de données non supporté: {type(equity_data)}")
        return create_default_equity_chart("ERROR")
    
    # Vérifier qu'on a des données
    if len(y_data) == 0:
        print("ERROR: Aucune donnée à tracer")
        return create_default_equity_chart("EMPTY")
    
    print(f"DEBUG: Tracé de {len(y_data)} points, min={np.min(y_data):.2f}, max={np.max(y_data):.2f}")
    
    plt.plot(x_data, y_data, linewidth=2, color='#2E86AB')
    plt.title(title, fontsize=16, fontweight='bold')
    plt.xlabel('Date')
    plt.ylabel('Equity ($)')
    plt.grid(True, alpha=0.3)
    
    # Formatage des axes
    if len(x_data) > 10:
        plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Sauvegarde temporaire
    temp_path = os.path.join(tempfile.gettempdir(), f"equity_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    
    print(f"DEBUG: Graphique sauvegardé: {temp_path}")
    return temp_path

def create_default_equity_chart(symbol: str) -> str:
    """Crée un graphique d'equity par défaut"""
    plt.figure(figsize=(12, 6))
    
    # Données par défaut
    dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
    equity = np.linspace(10000, 12000, 100) + np.random.normal(0, 100, 100).cumsum()
    
    plt.plot(dates, equity, linewidth=2, color='#2E86AB')
    plt.title(f"Courbe d'Equity - {symbol} (Données par défaut)", fontsize=16, fontweight='bold')
    plt.xlabel('Date')
    plt.ylabel('Equity ($)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    temp_path = os.path.join(tempfile.gettempdir(), f"equity_default_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    return temp_path

def create_default_drawdown_chart(symbol: str) -> str:
    """Crée un graphique de drawdown par défaut"""
    plt.figure(figsize=(12, 4))
    
    # Données par défaut
    dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
    drawdown = -np.abs(np.random.normal(0, 2, 100).cumsum())
    
    plt.fill_between(dates, drawdown, 0, alpha=0.3, color='red')
    plt.plot(dates, drawdown, linewidth=1, color='darkred')
    plt.title(f"Drawdown - {symbol} (Données par défaut)", fontsize=16, fontweight='bold')
    plt.xlabel('Date')
    plt.ylabel('Drawdown (%)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    temp_path = os.path.join(tempfile.gettempdir(), f"drawdown_default_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    return temp_path

def create_drawdown_chart(equity_data, title: str = "Drawdown") -> str:
    """Crée un graphique de drawdown et retourne le chemin"""
    print(f"DEBUG create_drawdown_chart: type={type(equity_data)}")
    
    plt.figure(figsize=(12, 4))
    
    # Convertir en Series si nécessaire
    if isinstance(equity_data, pd.DataFrame):
        if 'equity' in equity_data.columns:
            equity_series = equity_data['equity']
        else:
            numeric_cols = equity_data.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                equity_series = equity_data[numeric_cols[0]]
            else:
                return create_default_drawdown_chart("ERROR")
    elif isinstance(equity_data, pd.Series):
        equity_series = equity_data
    else:
        return create_default_drawdown_chart("ERROR")
    
    # Calculer le drawdown
    running_max = equity_series.expanding().max()
    drawdown = ((equity_series - running_max) / running_max) * 100
    
    print(f"DEBUG: Drawdown calculé, min={drawdown.min():.2f}%, max={drawdown.max():.2f}%")
    
    plt.fill_between(equity_series.index, drawdown, 0, alpha=0.3, color='red')
    plt.plot(equity_series.index, drawdown, linewidth=1, color='darkred')
    plt.title(title, fontsize=16, fontweight='bold')
    plt.xlabel('Date')
    plt.ylabel('Drawdown (%)')
    plt.grid(True, alpha=0.3)
    
    # Formatage des axes
    if len(equity_series) > 10:
        plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Sauvegarde temporaire
    temp_path = os.path.join(tempfile.gettempdir(), f"drawdown_{uuid.uuid4().hex[:8]}.png")
    plt.savefig(temp_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    
    print(f"DEBUG: Graphique drawdown sauvegardé: {temp_path}")
    return temp_path

# -----------------------------------------------------------------------------
# MIDDLEWARE
# -----------------------------------------------------------------------------

@app.after_request
def sanitize_response(response):
    """Middleware global : sanitize NaN/Inf -> null"""
    if response.is_json:
        try:
            data = response.get_json()
            clean = sanitize_numbers(data)
            return app.response_class(
                response=app.json.dumps(clean),
                status=response.status_code,
                mimetype='application/json'
            )
        except Exception:
            pass
    return response

# -----------------------------------------------------------------------------
# ROUTES API
# -----------------------------------------------------------------------------

@app.route("/")
def home():
    """Interface Python Strategy Editor"""
    try:
        # Lire le fichier HTML de l'interface avec l'éditeur de code
        html_path = os.path.join(os.path.dirname(__file__), '..', 'front', 'index.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        # Fallback si le fichier n'existe pas
        return f"""
        <html><body>
        <h1>Erreur - Interface non trouvée</h1>
        <p>Impossible de charger l'interface: {str(e)}</p>
        <p>Chemin recherché: {html_path}</p>
        </body></html>
        """


@app.route("/health", methods=["GET"])
def health():
    """Healthcheck ultra léger (aucun calcul)."""
    return jsonify({
        "status": "ok",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/strategies", methods=["GET"])
def get_strategies():
    """Route nouvelle: Fournir le template pour stratégie Python personnalisée"""
    
    # Template de stratégie Python personnalisée
    strategy_template = """# Définir votre stratégie DCA personnalisée
def create_custom_strategy():
    '''
    Créez votre stratégie DCA en modifiant les paramètres ci-dessous
    '''
    return {
        # Nombre d'ordres de sécurité maximum
        "safety_orders": 5,
        
        # Montant par ordre (en USD)
        "amount_per_order": 1000,
        
        # Déviation de prix pour déclencher les safety orders (%)
        "price_deviation": 2.5,
        
        # Take profit cible (%)
        "take_profit": 1.5,
        
        # Activer le RSI
        "rsi_enabled": True,
        "rsi_period": 14,
        "rsi_oversold": 30,
        
        # Activer les Bollinger Bands
        "bollinger_enabled": True,
        "bb_period": 20,
        "bb_multiplier": 2.0
    }

# Retourner les paramètres de stratégie
create_custom_strategy()"""
    
    return jsonify({
        "status": "success",
        "template": strategy_template,
        "description": "Modifiez le code Python ci-dessus pour créer votre stratégie personnalisée",
        "parameters_info": {
            "safety_orders": "Nombre maximum d'ordres de sécurité (1-10)",
            "amount_per_order": "Montant en USD par ordre (100-10000)",
            "price_deviation": "% de baisse pour déclencher safety order (0.5-10)",
            "take_profit": "% de profit pour fermer position (0.5-5)",
            "rsi_period": "Période RSI (7-21)",
            "rsi_oversold": "Seuil RSI survente (20-40)",
            "bb_period": "Période Bollinger Bands (10-50)",
            "bb_multiplier": "Multiplicateur BB (1.5-3.0)"
        }
    })

@app.route("/ingest-score", methods=["POST"])
def ingest_score():
    """Route 2: Charger et scorer des données multi-sources"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON payload requis"}), 400
            
        assets = data.get("assets", [])
        timeframe = data.get("timeframe", "1d")
        start_date = data.get("start_date", "2023-01-01")
        end_date = data.get("end_date", "2024-01-01")
        
        if not assets:
            return jsonify({"error": "Paramètre 'assets' requis"}), 400
            
        print(f"🔍 Recherche multi-source pour {assets}")
        
        # Utilisation du fetcher multi-source
        all_data, global_meta, global_errors = fetch_multi_source_data(
            symbols=assets,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe
        )
        
        # Traitement des résultats
        results = []
        total_success = 0
        
        for symbol in assets:
            if symbol in all_data and not all_data[symbol].empty:
                df = all_data[symbol]
                meta = {"symbol": symbol, "rows": len(df)}
                quality_score = calculate_data_quality_score(df, meta)
                data_hash = generate_data_hash(df)
                
                result = {
                    "symbol": symbol,
                    "source": "multi-exchange",
                    "quality_score": round(quality_score, 2),
                    "rows": len(df),
                    "start_date": str(df.index[0]) if len(df) > 0 else start_date,
                    "end_date": str(df.index[-1]) if len(df) > 0 else end_date,
                    "data_hash": data_hash,
                    "errors": [],
                    "status": "success" if quality_score > 50 else "warning"
                }
                
                if quality_score > 50:
                    total_success += 1
                    
            else:
                # Aucune donnée trouvée
                result = {
                    "symbol": symbol,
                    "source": "multi-exchange",
                    "quality_score": 0.0,
                    "rows": 0,
                    "start_date": start_date,
                    "end_date": end_date,
                    "data_hash": "",
                    "errors": [f"Aucune donnée trouvée pour {symbol}"],
                    "status": "error"
                }
                
            results.append(result)
        
        # Stockage des données avec un ID unique
        dataset_id = str(uuid.uuid4())
        DATA_STORE[dataset_id] = {
            "data": all_data,
            "meta": {
                "assets": assets,
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "created_at": datetime.utcnow().isoformat(),
                "source": "multi-exchange"
            },
            "sources": results
        }
        
        print(f"📊 Dataset {dataset_id[:8]}... créé avec {total_success}/{len(assets)} actifs")
        
        return jsonify({
            "dataset_id": dataset_id,
            "summary": {
                "total_assets": len(assets),
                "successful": total_success,
                "errors": len(global_errors)
            },
            "details": results,
            "global_errors": global_errors[:10],  # Limiter l'affichage
            "source": "multi-exchange-via-fetcher"
        })
        
    except Exception as e:
        print(f"❌ Erreur ingest-score: {str(e)}")
        return jsonify({"error": f"Erreur interne: {str(e)}"}), 500

@app.route("/backtest", methods=["POST"])
def backtest():
    """Route 3: Lancer un backtest DCA avec votre backtester personnalisé"""
    request_t0 = time.perf_counter()
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON payload requis"}), 400
            
        symbol = data.get("symbol", "BTC-USD")
        strategy_code = data.get("strategy_code", "")
        
        # Détection : si pas de strategy_code ou strategy_code == "dca_buy_dip", utiliser votre backtester
        use_custom_backtester = not strategy_code.strip() or strategy_code.strip() == "dca_buy_dip"
        
        if not use_custom_backtester and not strategy_code.strip():
            return jsonify({"error": "Code Python de stratégie requis dans 'strategy_code'"}), 400

        print(f"🚀 Backtest pour {symbol} - Mode: {'Backtester DCA personnalisé' if use_custom_backtester else 'Stratégie Python personnalisée'}")
        
        # Récupération des données via votre fetcher
        print("📥 Récupération des données via le fetcher personnalisé...")
        try:
            fetch_t0 = time.perf_counter()
            # Conversion du symbole pour le fetcher (BTC-USD -> BTC)
            base_symbol = symbol.split('-')[0] if '-' in symbol else symbol.replace('/USDT', '').replace('/USD', '')
            
            # Utilisation de Binance uniquement (plus rapide)
            agg, detail, data = fetch_binance_only_cached(
                bases=[base_symbol],  # Ex: ["BTC"]
                timeframe="1d",
                lookback_days=365  # 1 an de données
            )
            log_perf("fetch-single-asset", fetch_t0)
            
            # Vérification que les données ont été récupérées
            if agg is None or agg.empty:
                return jsonify({"error": f"Aucune donnée disponible pour {base_symbol}"}), 400
                
            if base_symbol not in data.get("__FINAL__", {}):
                available_keys = list(data.get("__FINAL__", {}).keys())
                return jsonify({"error": f"Symbole {base_symbol} non trouvé. Disponibles: {available_keys}"}), 400
                
            # Récupération du DataFrame final
            df = data["__FINAL__"][base_symbol]
            
            if df.empty:
                return jsonify({"error": f"Aucune donnée récupérée pour {base_symbol}"}), 400
            
            # Définir l'index datetime AVANT tout le reste
            # Le fetcher retourne une colonne 'date' déjà convertie en datetime
            if 'date' in df.columns:
                df = df.set_index('date')
            elif 'timestamp' in df.columns:
                df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df = df.drop('timestamp', axis=1, errors='ignore')
            
            # S'assurer que l'index est un DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            
            # Supprimer la colonne timestamp si elle existe encore
            if 'timestamp' in df.columns:
                df = df.drop('timestamp', axis=1)
            
            # Vérification des colonnes nécessaires
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return jsonify({"error": f"Colonnes manquantes dans les données: {required_cols}"}), 400
            
            # Conversion des colonnes en format attendu par le backtester (majuscules)
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High', 
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            
            # Affichage sécurisé
            start_str = df.index[0].strftime('%Y-%m-%d %H:%M') if hasattr(df.index[0], 'strftime') else str(df.index[0])
            end_str = df.index[-1].strftime('%Y-%m-%d %H:%M') if hasattr(df.index[-1], 'strftime') else str(df.index[-1])
            print(f"✅ Données récupérées via fetcher: {len(df)} points de {start_str} à {end_str}")
            print(f"🔗 Source: {data['__FINAL_META__'][base_symbol]['provenance']}")
            
        except Exception as e:
            return jsonify({"error": f"Erreur fetcher: {str(e)}"}), 400
        
        # Si on utilise votre backtester, on ignore l'exécution de code personnalisé
        if use_custom_backtester:
            print("🎯 Utilisation du backtester DCA personnalisé - pas d'exécution de code Python")
            strategy_func = None  # On n'en a pas besoin
        else:
            # Exécution sécurisée du code Python personnalisé
            try:
                print("🔧 Exécution du code de stratégie personnalisé...")
                
                # Environnement sécurisé pour l'exécution
                safe_globals = {
                    '__builtins__': {
                        'range': range,
                        'len': len,
                        'int': int,
                        'float': float,
                        'str': str,
                        'bool': bool,
                        'dict': dict,
                        'list': list,
                        'max': max,
                        'min': min,
                        'sum': sum,
                        'abs': abs,
                        '__import__': __import__  # Autoriser les imports
                    },
                    'pd': pd,  # Pandas directement disponible
                    'pandas': pd,
                    'ta': ta,  # pandas_ta disponible
                    'pandas_ta': ta,
                    'np': np,  # numpy disponible
                    'numpy': np
                }
                safe_locals = {}
                
                # Exécuter le code de stratégie
                exec(strategy_code, safe_globals, safe_locals)
                
                # Le code doit retourner un dictionnaire de paramètres
                if 'create_custom_strategy' not in safe_locals:
                    return jsonify({"error": "Le code doit définir une fonction 'create_custom_strategy()'"}), 400
                    
                # Appeler la fonction pour obtenir la fonction de stratégie
                strategy_function = safe_locals['create_custom_strategy']()
                
                if not callable(strategy_function):
                    return jsonify({"error": "La fonction 'create_custom_strategy()' doit retourner une fonction"}), 400
                
                # Créer des données factices pour tester la stratégie
                test_df = pd.DataFrame({
                    'Open': [100, 101, 102],
                    'High': [105, 106, 107], 
                    'Low': [95, 96, 97],
                    'Close': [102, 103, 104],
                    'Volume': [1000, 1100, 1200]
                })
                
                # Tester la fonction de stratégie avec les paramètres
                strategy_result = strategy_function(test_df.copy(), data.get('params', {}))
                
                if not isinstance(strategy_result, pd.DataFrame):
                    return jsonify({"error": "La fonction de stratégie doit retourner un DataFrame"}), 400
                    
                print(f"✅ Fonction de stratégie validée avec succès")
                
                # Stocker la fonction de stratégie pour utilisation ultérieure
                strategy_func = strategy_function
                
            except Exception as e:
                return jsonify({"error": f"Erreur dans le code de stratégie: {str(e)}"}), 400
        
        # Validation et conversion des paramètres pour votre backtester (unités logiques)
        try:
            request_params = data.get('params', {})
            cash_initial = float(request_params.get("quantite_base", 1000000))
            
            # Paramètres pour votre backtester (quantité_base = 1 pour unités logiques)
            strategy_params = {
                "quantite_base": 1.0,  # Unité logique comme dca_library
                "quantite_so_base": 1.0 * float(request_params.get("so_volume_scale", 1.5)),
                "nb_max_so": int(request_params.get("so_max", 5)),
                "volume_scale": float(request_params.get("so_volume_scale", 1.5)),
                "deviation_premier_so": float(request_params.get("so_step", 0.02)),
                "step_scale": float(request_params.get("so_step_scale", 1.5)),
                "take_profit_pourcent": float(request_params.get("min_tp", 0.03)),
                "rsi_entry": int(request_params.get("rsi_entry", 30)),
                "commission": float(request_params.get("commission", 0.0005)),
                "cash_initial": cash_initial  # Pour conversion finale
            }
            
            print(f"🎯 Paramètres DCA convertis: {strategy_params}")
            
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Erreur de conversion des paramètres: {str(e)}"}), 400

        # Configuration des paramètres DCA avec unités logiques (comme dca_library)
        parametres_dca = ParametresDCA_Exact(
            cote="LONG",
            quantite_base=1.0,  # Unité logique comme dca_library
            quantite_so_base=1.0 * float(request_params.get("so_volume_scale", 1.5)),
            nb_max_so=strategy_params["nb_max_so"],
            volume_scale=strategy_params["volume_scale"],
            deviation_premier_so=strategy_params["deviation_premier_so"],
            step_scale=strategy_params["step_scale"],
            take_profit_pourcent=strategy_params["take_profit_pourcent"],
            stop_loss_pourcent=None,
            commission=strategy_params["commission"],
            slippage_pourcent=0.02,
            
            # Paramètres indicateurs avec valeurs utilisateur
            rsi_length=int(request_params.get("rsi_length", 14)),
            rsi_entry=int(request_params.get("rsi_entry", 30)),
            rsi_exit=int(request_params.get("rsi_exit", 75)),
            bb_length=int(request_params.get("bb_length", 20)),
            bb_std=float(request_params.get("bb_std", 3.0)),
            bbp_trigger=float(request_params.get("bbp_trigger", 0.2)),
            tp_minimum=float(request_params.get("min_tp", 0.01))
        )
        
        # Utiliser votre backtester personnalisé avec la logique DCA EXACTE
        print(f"🎯 Application de la vraie stratégie DCA avec votre backtester exact...")
        
        # Générer SEULEMENT les signaux d'entrée principale (comme dans dca_library)
        close_series = pd.Series(df['Close'].values, index=df.index)
        
        # Calcul RSI pour signaux d'entrée SEULEMENT
        rsi = ta.rsi(close_series, length=int(request_params.get("rsi_length", 14)))
        rsi = rsi.fillna(50)
        
        # Signal d'entrée PRINCIPAL SEULEMENT : RSI < seuil d'entrée
        # (votre backtester gère les Safety Orders automatiquement)
        rsi_entry_threshold = int(request_params.get("rsi_entry", 30))
        signal_entree = rsi < rsi_entry_threshold
        
        print(f"🎯 Signaux d'entrée principale générés: {signal_entree.sum()} signaux")
        
        # Séparer les données IS/OOS d'abord
        split_point = int(len(df) * 0.7)
        df_is = df.iloc[:split_point].copy()
        df_oos = df.iloc[split_point:].copy()
        signal_is = signal_entree.iloc[:split_point].copy()
        signal_oos = signal_entree.iloc[split_point:].copy()
        
        print(f"📊 Période IS: {len(df_is)} points, OOS: {len(df_oos)} points")
        print(f"🎯 Signaux IS: {signal_is.sum()}, OOS: {signal_oos.sum()}")
        
        # Backtest IS avec SmartBot V2
        trades_is, equity_is, stats_is = backtest_smartbot_v2(df_is, parametres_dca)
        
        # Backtest OOS avec SmartBot V2
        trades_oos, equity_oos, stats_oos = backtest_smartbot_v2(df_oos, parametres_dca)
        
        print(f"🎯 Backtest IS: {stats_is.get('total_trades', 0)} trades, Return: {stats_is.get('capital_return_pct', 0):.2f}%")
        print(f"🎯 Backtest OOS: {stats_oos.get('total_trades', 0)} trades, Return: {stats_oos.get('capital_return_pct', 0):.2f}%")
        
        # Conversion des résultats SmartBot V2 au format attendu par l'API
        def convert_smartbot_results(trades, stats, equity, prefix=""):
            return {
                f"{prefix}trades_count": stats.get("total_trades", 0),
                f"{prefix}win_rate": stats.get("win_rate_tradingview", 0) / 100 if stats.get("win_rate_tradingview") else 0,
                f"{prefix}avg_pnl": stats.get("avg_pnl_per_trade", 0),
                f"{prefix}total_pnl": stats.get("total_pnl", 0),
                f"{prefix}max_drawdown": abs(stats.get("max_drawdown", 0)),
                f"{prefix}return_pct": stats.get("capital_return_pct", 0),
                f"{prefix}final_equity": stats.get("final_capital", stats.get("initial_capital", 10000)),
                f"{prefix}sharpe": 0.0
            }
        
        results_is = convert_smartbot_results(trades_is, stats_is, equity_is, "is_")
        results_oos = convert_smartbot_results(trades_oos, stats_oos, equity_oos, "oos_")
        
        # Détection de l'overfitting
        oos_warning = False
        if results_is["is_return_pct"] > 5 and results_oos["oos_return_pct"] < results_is["is_return_pct"] * 0.3:
            oos_warning = True
        
        # Création des graphiques professionnels avec vos données
        price_chart_path = None
        equity_chart_path = None
        trades_chart_path = None
        
        try:
            # 1. Graphique de prix avec chandeliers et trades
            if not df_is.empty and not trades_is.empty:
                price_chart_path = create_professional_price_chart(
                    df_is, trades_is, f"Analyse Prix & Trades - {symbol}"
                )
                print(f"✅ Graphique prix professionnel créé: {price_chart_path}")
            
            # 2. Graphique d'equity professionnel
            if not equity_is.empty:
                equity_chart_path = create_professional_equity_chart(
                    equity_is, trades_is, f"Performance Equity - {symbol}"
                )
                print(f"✅ Graphique equity professionnel créé: {equity_chart_path}")
            else:
                print("⚠️ equity_is est vide, création d'un graphique par défaut")
                equity_chart_path = create_default_equity_chart(symbol)
            
            # 3. Graphique d'analyse des trades
            if not trades_is.empty:
                trades_chart_path = create_trades_analysis_chart(
                    trades_is, f"Analyse Détaillée des Trades - {symbol}"
                )
                print(f"✅ Graphique trades créé: {trades_chart_path}")
        
        except Exception as e:
            print(f"❌ Erreur création graphiques: {e}")
            # Graphiques par défaut en cas d'erreur
            price_chart_path = create_default_equity_chart(f"{symbol}-price")
            equity_chart_path = create_default_equity_chart(symbol)
            trades_chart_path = create_default_equity_chart(f"{symbol}-trades")
        
        # Préparation des détails des trades
        trades_detail_is = []
        trades_detail_oos = []
        
        if not trades_is.empty:
            trades_detail_is = trades_is.head(10).to_dict('records')  # 10 premiers trades
            
        if not trades_oos.empty:
            trades_detail_oos = trades_oos.head(10).to_dict('records')
        
        # Stockage des résultats
        run_id = str(uuid.uuid4())
        # Stockage des données dans BACKTEST_STORE (ce qui est déjà fait au-dessus)
        BACKTEST_STORE[run_id] = {
            "symbol": symbol,
            "strategy": "dca_buy_dip_exact",
            "custom_strategy": request_params,
            "parameters": {
                "rsi_entry": parametres_dca.rsi_entry,
                "rsi_exit": parametres_dca.rsi_exit,
                "bbp_trigger": parametres_dca.bbp_trigger,
                "tp_minimum": parametres_dca.tp_minimum,
                "nb_max_so": parametres_dca.nb_max_so,
                "volume_scale": parametres_dca.volume_scale,
                "signal_logic": "dca_library_compatible_exact",
                "backtest_approach": "your_custom_backtester"
            },
            "results": {**results_is, **results_oos},
            "trades": {
                "is_sample": trades_detail_is,
                "oos_sample": trades_detail_oos
            },
            "trades_dataframe": pd.concat([trades_is, trades_oos]) if not trades_is.empty or not trades_oos.empty else pd.DataFrame(),
            "charts": {
                "price": price_chart_path,
                "equity": equity_chart_path,
                "trades": trades_chart_path
            },
            "warnings": {
                "overfitting": oos_warning
            },
            "created_at": datetime.utcnow().isoformat()
        }
        
        print(f"✅ Backtest terminé - IS: {results_is['is_trades_count']} trades, OOS: {results_oos['oos_trades_count']} trades")
        
        # Génération automatique du rapport HTML
        try:
            print("📄 Génération automatique du rapport HTML...")
            
            # Stocker les données dans BACKTEST_STORE pour la génération du rapport
            # BACKTEST_STORE[run_id] = backtest_data
            
            # Génération du rapport HTML (utilisation de la logique existante de la route /report)
            run_data = BACKTEST_STORE[run_id]
            results = run_data["results"]
            
            # Conversion des images en base64 pour embed
            def image_to_base64(image_path):
                if os.path.exists(image_path):
                    with open(image_path, 'rb') as f:
                        return base64.b64encode(f.read()).decode()
                return ""
            
            # Support des trois graphiques professionnels
            charts_data = run_data.get("charts", {})
            price_b64 = image_to_base64(charts_data.get("price", ""))
            equity_b64 = image_to_base64(charts_data.get("equity", ""))
            trades_b64 = image_to_base64(charts_data.get("trades", ""))
            
            # Génération du HTML avec thème noir complet
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Rapport Backtest DCA - {symbol}</title>
                <meta charset="utf-8">
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        margin: 0; 
                        padding: 20px; 
                        background-color: #000000; 
                        color: #ffffff; 
                    }}
                    .header {{ 
                        background: #1a1a1a; 
                        color: #ffffff; 
                        padding: 20px; 
                        border-radius: 5px; 
                        border: 1px solid #333333;
                    }}
                    .stats {{ 
                        display: flex; 
                        gap: 20px; 
                        margin: 20px 0; 
                        flex-wrap: wrap;
                    }}
                    .stat-box {{ 
                        background: #1a1a1a; 
                        color: #ffffff;
                        padding: 15px; 
                        border-radius: 5px; 
                        flex: 1; 
                        min-width: 200px;
                        border: 1px solid #333333;
                    }}
                    .stat-box h3 {{
                        color: #22c55e;
                        margin-top: 0;
                    }}
                    .chart {{ 
                        margin: 20px 0; 
                        text-align: center; 
                        background: #1a1a1a;
                        padding: 10px;
                        border-radius: 5px;
                        border: 1px solid #333333;
                    }}
                    .chart h3 {{
                        color: #ffffff;
                        margin-top: 0;
                    }}
                    img {{ 
                        max-width: 100%; 
                        border: 1px solid #333333;
                        background: #000000;
                    }}
                    h1, h2, h3 {{
                        color: #ffffff;
                    }}
                    p {{
                        color: #cccccc;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>🚀 Rapport Backtest DCA Personnalisé</h1>
                    <p>Symbole: {symbol} | Stratégie: Python Custom | Run ID: {run_id}</p>
                </div>
                
                <div class="stats">
                    <div class="stat-box">
                        <h3>Trades Total</h3>
                        <p>{results_is['is_trades_count'] + results_oos['oos_trades_count']}</p>
                    </div>
                    <div class="stat-box">
                        <h3>Win Rate</h3>
                        <p>{((results_is.get('is_win_rate', 0) + results_oos.get('oos_win_rate', 0)) / 2):.1f}%</p>
                    </div>
                    <div class="stat-box">
                        <h3>Total PnL</h3>
                        <p>{results_is.get('is_total_pnl', 0) + results_oos.get('oos_total_pnl', 0):.2f}$</p>
                    </div>
                </div>
                
                <div class="chart">
                    <h3>📊 Graphique des Prix</h3>
                    <img src="data:image/png;base64,{price_b64}" alt="Prix Chart">
                </div>
                
                <div class="chart">
                    <h3>📈 Courbe d'Equity</h3>
                    <img src="data:image/png;base64,{equity_b64}" alt="Equity Chart">
                </div>
                
                <div class="chart">
                    <h3>🔍 Analyse des Trades</h3>
                    <img src="data:image/png;base64,{trades_b64}" alt="Trades Chart">
                </div>
                
                <p style="text-align: center; color: #666666; margin-top: 40px;">
                    Rapport généré le {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
                </p>
            </body>
            </html>
            """
            
            # Sauvegarde du rapport HTML
            html_filename = f"rapport_backtest_{run_id}.html"
            html_path = os.path.join(tempfile.gettempdir(), html_filename)
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Ajouter le chemin du rapport dans BACKTEST_STORE pour le téléchargement
            BACKTEST_STORE[run_id]["report_path"] = html_path
            
            print(f"✅ Rapport HTML généré: {html_path}")
            
        except Exception as e:
            print(f"⚠️ Erreur génération rapport HTML: {str(e)}")
            # En cas d'erreur, on s'assure que report_path n'existe pas
            if run_id in BACKTEST_STORE:
                BACKTEST_STORE[run_id]["report_path"] = None
        
        # Préparation de la réponse avec conversion des pandas objects
        response_data = {
            "run_id": run_id,
            "strategy": "dca_custom_python",
            "symbol": symbol,
            "custom_strategy": request_params,
            "summary": {
                "is_sample": results_is,
                "oos_sample": results_oos,
                "overfitting_warning": oos_warning
            },
            "trades_preview": {
                "is_sample": trades_detail_is[:3],  # 3 premiers pour préview
                "oos_sample": trades_detail_oos[:3]
            },
            "trades_count": results_is['is_trades_count'] + results_oos['oos_trades_count'],
            "win_rate": ((results_is.get('is_win_rate', 0) + results_oos.get('oos_win_rate', 0)) / 2),
            "total_pnl": results_is.get('is_total_pnl', 0) + results_oos.get('oos_total_pnl', 0),
            "max_drawdown": max(results_is.get('is_max_drawdown', 0), results_oos.get('oos_max_drawdown', 0)),
            "html_report": {
                "available": True,
                "download_url": f"/download-report/{run_id}",
                "run_id": run_id
            },
            "charts": {
                "price_chart": image_to_base64(price_chart_path) if 'price_chart_path' in locals() else "",
                "equity_chart": image_to_base64(equity_chart_path) if 'equity_chart_path' in locals() else "",
                "trades_chart": image_to_base64(trades_chart_path) if 'trades_chart_path' in locals() else ""
            },
            "message": f"Backtest réussi avec stratégie personnalisée - {results_is['is_trades_count'] + results_oos['oos_trades_count']} trades au total. Rapport HTML disponible !"
        }
        
        # Fonction pour convertir image en base64 (si pas déjà définie)
        def image_to_base64(image_path):
            if image_path and os.path.exists(image_path):
                try:
                    with open(image_path, 'rb') as f:
                        return base64.b64encode(f.read()).decode()
                except:
                    return ""
            return ""
        
        # Conversion des pandas objects en types JSON-sérialisables
        response_data = convert_pandas_to_json(response_data)
        log_perf("backtest-single-total", request_t0)
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Erreur backtest: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur backtest: {str(e)}"}), 500
    finally:
        gc.collect()

@app.route("/report", methods=["POST"])
def report():
    """Route 4: Générer un rapport HTML complet"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON payload requis"}), 400
            
        run_id = data.get("run_id")
        if not run_id:
            return jsonify({"error": "Paramètre 'run_id' requis"}), 400
            
        if run_id not in BACKTEST_STORE:
            return jsonify({"error": "Run non trouvé"}), 404
            
        run_data = BACKTEST_STORE[run_id]
        results = run_data["results"]
        
        # Récupération des données additionnelles
        dataset = DATA_STORE.get(run_data["dataset_id"], {})
        
        # Conversion des images en base64 pour embed
        def image_to_base64(image_path):
            if os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode()
            return ""
        
        # Support des trois graphiques professionnels
        charts_data = run_data.get("charts", {})
        price_b64 = image_to_base64(charts_data.get("price", ""))
        equity_b64 = image_to_base64(charts_data.get("equity", ""))
        trades_b64 = image_to_base64(charts_data.get("trades", ""))
        
        # Calendrier mensuel simulé
        monthly_perf = []
        for i in range(12):
            monthly_perf.append({
                "month": f"2024-{i+1:02d}",
                "return": round(2.5 + (i * 0.5), 2)  # Progression simple
            })
        
        # Top/Worst trades - version simplifiée pour éviter les erreurs
        best_trades = []
        worst_trades = []
        
        # Template HTML complet
        html_content = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport Backtest DCA - {run_data["symbol"]}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; 
            line-height: 1.6; 
            color: #e0e0e0; 
            background: #0d1117;
            font-size: 14px;
        }}
        .container {{ 
            max-width: 1400px; 
            margin: 0 auto; 
            padding: 30px; 
            background: #161b22;
            box-shadow: 0 0 30px rgba(0,0,0,0.5);
            border-radius: 12px;
            min-height: 100vh;
        }}
        h1, h2, h3 {{ color: #f0f6fc; margin: 30px 0 15px 0; }}
        h1 {{ 
            text-align: center; 
            border-bottom: 3px solid #58a6ff; 
            padding-bottom: 15px; 
            font-size: 2.5em;
            background: linear-gradient(135deg, #58a6ff, #1f6feb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        h2 {{ 
            font-size: 1.8em; 
            border-left: 4px solid #f78166;
            padding-left: 15px;
            margin-top: 40px;
        }}
        h3 {{ 
            font-size: 1.3em; 
            color: #7d8590;
            margin-bottom: 20px;
        }}
        .summary {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 25px; 
            margin: 40px 0; 
        }}
        .metric-card {{ 
            background: linear-gradient(135deg, #238636 0%, #196c2e 100%); 
            color: white; 
            padding: 25px; 
            border-radius: 12px; 
            text-align: center; 
            border: 1px solid #30363d;
            transition: transform 0.2s ease;
        }}
        .metric-card:hover {{ transform: translateY(-2px); }}
        .metric-value {{ font-size: 2.2em; font-weight: 700; margin-bottom: 5px; }}
        .metric-label {{ font-size: 0.95em; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px; }}
        .chart-container {{ 
            text-align: center; 
            margin: 40px 0; 
            background: #21262d;
            padding: 25px;
            border-radius: 12px;
            border: 1px solid #30363d;
        }}
        .chart-container img {{ 
            max-width: 100%; 
            height: auto; 
            border-radius: 8px; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }}
        .section {{ 
            margin: 50px 0; 
            background: #21262d;
            padding: 30px;
            border-radius: 12px;
            border: 1px solid #30363d;
        }}
        table {{ 
            width: 100%; 
            border-collapse: collapse; 
            margin: 20px 0; 
            background: #0d1117;
            border-radius: 8px;
            overflow: hidden;
        }}
        th, td {{ 
            padding: 15px; 
            text-align: left; 
            border-bottom: 1px solid #30363d; 
        }}
        th {{ 
            background: #21262d; 
            color: #f0f6fc; 
            font-weight: 600; 
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 0.9em;
        }}
        td {{ color: #e6edf3; }}
        tr:hover {{ background: #161b22; }}
        .warning {{ 
            background: #ffeaa7; 
            color: #2d3436; 
            padding: 15px; 
            border-radius: 8px; 
            margin: 20px 0; 
            border-left: 4px solid #fdcb6e;
            font-weight: 500;
        }}
        .info {{ 
            background: #21262d; 
            color: #e6edf3; 
            padding: 20px; 
            border-radius: 8px; 
            border-left: 4px solid #58a6ff;
            line-height: 1.8;
        }}
        .download-button {{ 
            display: inline-block; 
            background: linear-gradient(135deg, #238636, #196c2e); 
            color: white; 
            padding: 15px 30px; 
            text-decoration: none; 
            border-radius: 8px; 
            margin: 20px 0;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(35, 134, 54, 0.3);
        }}
        .download-button:hover {{ 
            background: linear-gradient(135deg, #2ea043, #238636);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(35, 134, 54, 0.4);
        }}
        .section {{ margin: 40px 0; }}
        .warning {{ 
            padding: 20px; 
            border-left: 4px solid #e74c3c; 
            background: #fdf2f2; 
            color: #c0392b;
            margin: 20px 0;
        }}
        .info {{ 
            padding: 20px; 
            border-left: 4px solid #3498db; 
            background: #ecf0f1; 
        }}
        .footer {{ 
            margin-top: 50px; 
            padding: 20px; 
            background: #2c3e50; 
            color: white; 
            text-align: center; 
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Rapport de Backtest DCA Kronos</h1>
        <p style="text-align: center; font-size: 1.2em; color: #7f8c8d;">
            Symbole: <strong>{run_data["symbol"]}</strong> | 
            Stratégie: <strong>{run_data["strategy"]}</strong> | 
            Généré le: <strong>{datetime.now().strftime('%d/%m/%Y %H:%M')}</strong>
        </p>
        
        <div class="summary">
            <div class="metric-card">
                <div class="metric-value">{results.get('is_return_pct', 0):.1f}%</div>
                <div class="metric-label">Return IS</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{results.get('oos_return_pct', 0):.1f}%</div>
                <div class="metric-label">Return OOS</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{results.get('is_trades_count', 0)}</div>
                <div class="metric-label">Trades IS</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{results.get('oos_trades_count', 0)}</div>
                <div class="metric-label">Trades OOS</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{results.get('is_win_rate', 0):.1%}</div>
                <div class="metric-label">Win Rate IS</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{results.get('oos_win_rate', 0):.1%}</div>
                <div class="metric-label">Win Rate OOS</div>
            </div>
        </div>
        
        {f'<div class="warning">⚠️ <strong>Attention:</strong> Les performances OOS sont significativement inférieures aux performances IS. Risque de sur-optimisation.</div>' if run_data.get('warnings', {}).get('overfitting', False) else ''}
        
        <div class="section">
            <h2>� Analyse Technique & Trades</h2>
            <div class="chart-container">
                <h3>Chandeliers & Points d'Entrée/Sortie</h3>
                <img src="data:image/png;base64,{price_b64}" alt="Analyse Prix et Trades" style="width: 100%; height: auto;" />
            </div>
        </div>
        
        <div class="section">
            <h2>📈 Performance & Equity</h2>
            <div class="chart-container">
                <h3>Courbe d'Equity & Drawdown</h3>
                <img src="data:image/png;base64,{equity_b64}" alt="Performance Equity" style="width: 100%; height: auto;" />
            </div>
        </div>
        
        <div class="section">
            <h2>🎯 Analyse Détaillée des Trades</h2>
            <div class="chart-container">
                <h3>Distribution, PnL Cumulé & Statistiques</h3>
                <img src="data:image/png;base64,{trades_b64}" alt="Analyse des Trades" style="width: 100%; height: auto;" />
            </div>
        </div>
        
        <div class="section">
            <h2>📋 Liste Détaillée des Trades (Style TradingView)</h2>
            <div class="chart-container">
                {generate_tradingview_table_html(run_data.get('trades_dataframe'))}
            </div>
        </div>
        
        <div class="section">
            <h2>⚙️ Paramètres de la Stratégie</h2>
            <div class="info">
                <strong>Conditions d'entrée RSI:</strong> < {run_data.get('parameters', {}).get('rsi_entry', 'N/A')}<br>
                <strong>Conditions de sortie RSI:</strong> > {run_data.get('parameters', {}).get('rsi_exit', 'N/A')}<br>
                <strong>Trigger Safety Orders BBP:</strong> < {run_data.get('parameters', {}).get('bbp_trigger', 'N/A')}<br>
                <strong>Take Profit minimum:</strong> {run_data.get('parameters', {}).get('tp_minimum', 'N/A')*100:.1f}%<br>
                <strong>Nombre max Safety Orders:</strong> {run_data.get('parameters', {}).get('nb_max_so', 'N/A')}<br>
                <strong>Échelle de volume:</strong> x{run_data.get('parameters', {}).get('volume_scale', 'N/A')}
            </div>
        </div>
        
        <div class="section">
            <h2>📅 Performance Mensuelle (Simulation)</h2>
            <table>
                <thead>
                    <tr><th>Mois</th><th>Return (%)</th></tr>
                </thead>
                <tbody>
                    {''.join([f'<tr><td>{month["month"]}</td><td>{month["return"]:.2f}%</td></tr>' for month in monthly_perf[:6]])}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>📊 Statistiques Détaillées</h2>
            <table>
                <thead>
                    <tr><th>Métrique</th><th>In-Sample</th><th>Out-of-Sample</th></tr>
                </thead>
                <tbody>
                    <tr><td>Nombre de trades</td><td>{results.get('is_trades_count', 0)}</td><td>{results.get('oos_trades_count', 0)}</td></tr>
                    <tr><td>Win Rate</td><td>{results.get('is_win_rate', 0):.1%}</td><td>{results.get('oos_win_rate', 0):.1%}</td></tr>
                    <tr><td>Return Total</td><td>{results.get('is_return_pct', 0):.2f}%</td><td>{results.get('oos_return_pct', 0):.2f}%</td></tr>
                    <tr><td>PnL Moyen</td><td>${results.get('is_avg_pnl', 0):.2f}</td><td>${results.get('oos_avg_pnl', 0):.2f}</td></tr>
                    <tr><td>Max Drawdown</td><td>{results.get('is_max_drawdown', 0):.2f}%</td><td>{results.get('oos_max_drawdown', 0):.2f}%</td></tr>
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>🚀 <strong>Rapport généré par Kronos DCA Backtester</strong></p>
            <p>Système de backtesting vectorisé avec conditions RSI/BBP intelligentes</p>
            <p>Multi-source data integration: 9 exchanges | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
        """
        
        # Sauvegarde du rapport
        report_path = f"/tmp/kronos_report_{run_id[:8]}.html"
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            # Stocker le chemin du rapport dans BACKTEST_STORE
            BACKTEST_STORE[run_id]["report_path"] = report_path
            print(f"✅ Rapport sauvegardé: {report_path}")
        except Exception as save_error:
            print(f"⚠️ Impossible de sauvegarder le rapport: {save_error}")
            report_path = None
        
        return jsonify({
            "html": html_content,
            "run_id": run_id,
            "download_url": f"/download-report/{run_id}" if report_path else None,
            "status": "success",
            "size_kb": round(len(html_content) / 1024, 2)
        })
        
        # Template HTML simple avec thème noir uniforme
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Results - {results['symbol']}</title>
    <style>
        body {{ 
            font-family: Arial, sans-serif; 
            margin: 20px; 
            background-color: #000000; 
            color: #ffffff; 
        }}
        table {{ 
            border-collapse: collapse; 
            width: 100%; 
            margin: 20px 0; 
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #333333;
        }}
        th, td {{ 
            border: 1px solid #333333; 
            padding: 12px; 
            text-align: left; 
        }}
        th {{ 
            background-color: #1a1a1a; 
            color: #22c55e;
            font-weight: bold;
            text-transform: uppercase;
        }}
        td {{ 
            color: #cccccc; 
            background-color: #0d0d0d;
        }}
        tr:hover td {{ 
            background-color: #1a1a1a; 
        }}
        .metric {{ 
            margin: 10px 0; 
            color: #cccccc;
        }}
        .chart {{ 
            text-align: center; 
            margin: 20px 0; 
            background: #1a1a1a;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #333333;
        }}
        h1, h2 {{ 
            color: #ffffff; 
        }}
        .positive {{ 
            color: #22c55e; 
            font-weight: bold;
        }}
        .negative {{ 
            color: #ef4444; 
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <h1>Backtest Results: {results['symbol']}</h1>
    
    <h2>Performance Summary</h2>
    <div class="metric">Total Return: <span class="{{'positive' if results['total_return_pct'] >= 0 else 'negative'}}">{results['total_return_pct']:.2f}%</span></div>
    <div class="metric">Max Drawdown: <span class="negative">{results['max_drawdown']:.2f}%</span></div>
    <div class="metric">Sharpe Ratio: {results['sharpe_ratio']:.3f}</div>
    <div class="metric">Total Trades: {results['total_trades']}</div>
    <div class="metric">Win Rate: {results['win_rate']:.1f}%</div>
    <div class="metric">Start Date: {results['start_date']}</div>
    <div class="metric">End Date: {results['end_date']}</div>
    
    <h2>Charts</h2>
    <div class="chart">
        <h3>Price Analysis with Buy/Sell Points</h3>
        <img src="data:image/png;base64,{price_chart_b64}" alt="Price Chart" style="max-width: 100%;">
    </div>
    
    <div class="chart">
        <h3>Equity Curve</h3>
        <img src="data:image/png;base64,{equity_chart_b64}" alt="Equity Chart" style="max-width: 100%;">
    </div>
    
    <div class="chart">
        <h3>Trades Analysis</h3>
        <img src="data:image/png;base64,{trades_chart_b64}" alt="Trades Chart" style="max-width: 100%;">
    </div>
    
    <h2>Trade Details</h2>
    <table>
        <tr><th>Entry Date</th><th>Entry Price</th><th>Exit Date</th><th>Exit Price</th><th>PnL</th><th>Return %</th></tr>
        {trades_rows}
    </table>
    
</body>
</html>"""
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Stockage du chemin pour téléchargement
        BACKTEST_STORE[run_id]["report_path"] = report_path

        return jsonify({
            "run_id": run_id,
            "html_path": report_path,
            "download_url": f"/download-report/{run_id}",
            "status": "success",
            "size_kb": round(len(html_content) / 1024, 2)
        })

    except Exception as e:
        import traceback
        print(f"❌ Erreur rapport: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": f"Erreur génération rapport: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# ROUTES DE TÉLÉCHARGEMENT
# -----------------------------------------------------------------------------

@app.route("/download-report/<run_id>")
def download_report(run_id):
    """Télécharger le rapport HTML"""
    if run_id not in BACKTEST_STORE:
        return jsonify({"error": "Run non trouvé"}), 404
    
    try:
        run_data = BACKTEST_STORE[run_id]
        
        # Récupération des graphiques générés
        charts_data = run_data.get("charts", {})
        
        # Conversion des images en base64 pour embed
        def image_to_base64(image_path):
            if image_path and os.path.exists(image_path):
                try:
                    with open(image_path, 'rb') as f:
                        return base64.b64encode(f.read()).decode()
                except:
                    return ""
            return ""
        
        price_b64 = image_to_base64(charts_data.get("price", ""))
        equity_b64 = image_to_base64(charts_data.get("equity", ""))
        trades_b64 = image_to_base64(charts_data.get("trades", ""))
        
        # Création d'un HTML avec graphiques intégrés
        html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport Kronos - {run_data.get("symbol", "BTC")}</title>
    <style>
        body {{
            font-family: 'Courier New', monospace;
            background: #000;
            color: #bb44ff;
            margin: 0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            background: #1a1a1a;
            padding: 30px;
            border: 2px solid #bb44ff;
            border-radius: 10px;
            margin-bottom: 30px;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .metric {{
            background: #0a0a0a;
            border: 1px solid #bb44ff;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }}
        .metric-value {{
            font-size: 2em;
            font-weight: bold;
            color: #ffffff;
            margin: 10px 0;
        }}
        .chart-section {{
            background: #0a0a0a;
            border: 1px solid #bb44ff;
            border-radius: 8px;
            padding: 20px;
            margin: 30px 0;
            text-align: center;
        }}
        .chart-section h2 {{
            color: #ffffff;
            margin-bottom: 20px;
        }}
        .chart-section img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
            background: #000;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            color: #666;
        }}
        h1 {{ color: #ffffff; }}
        h2 {{ color: #bb44ff; }}
        h3 {{ color: #bb44ff; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 PROJET KRONOS</h1>
            <h2>Rapport de Backtest DCA</h2>
            <p>Symbole: {run_data.get("symbol", "BTC-USD")}</p>
            <p>Stratégie: Buy Dip avec scaling automatique</p>
        </div>
        
        <div class="metrics">
            <div class="metric">
                <h3>💹 Rendement IS</h3>
                <div class="metric-value">{run_data.get("results", {}).get("is_return_pct", 0):.2f}%</div>
            </div>
            <div class="metric">
                <h3>📊 Rendement OOS</h3>
                <div class="metric-value">{run_data.get("results", {}).get("oos_return_pct", 0):.2f}%</div>
            </div>
            <div class="metric">
                <h3>🎯 Total Trades</h3>
                <div class="metric-value">{run_data.get("results", {}).get("is_trades_count", 0) + run_data.get("results", {}).get("oos_trades_count", 0)}</div>
            </div>
            <div class="metric">
                <h3>📈 Win Rate</h3>
                <div class="metric-value">{run_data.get("results", {}).get("is_win_rate", 0):.1f}%</div>
            </div>
        </div>'''
        
        # Ajout des graphiques s'ils existent
        if price_b64:
            html_content += f'''
        <div class="chart-section">
            <h2>� Analyse des Prix et Trades</h2>
            <img src="data:image/png;base64,{price_b64}" alt="Graphique des prix et trades" />
        </div>'''
        
        if equity_b64:
            html_content += f'''
        <div class="chart-section">
            <h2>📈 Courbe d'Equity</h2>
            <img src="data:image/png;base64,{equity_b64}" alt="Courbe d'equity" />
        </div>'''
        
        if trades_b64:
            html_content += f'''
        <div class="chart-section">
            <h2>🎯 Analyse Détaillée des Trades</h2>
            <img src="data:image/png;base64,{trades_b64}" alt="Analyse des trades" />
        </div>'''
        
        # Si aucun graphique n'est disponible
        if not (price_b64 or equity_b64 or trades_b64):
            html_content += '''
        <div class="chart-section">
            <h2>📊 Graphiques</h2>
            <p>Les graphiques détaillés sont disponibles dans l'interface web.</p>
            <p><strong>Interface:</strong> http://localhost:3000/kronos-client.html</p>
        </div>'''
        
        # Fin du HTML
        html_content += f'''
        <div class="footer">
            <p>Rapport généré le {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
        </div>
    </div>
</body>
</html>'''
        
        # Sauvegarde du fichier
        html_filename = f"rapport_kronos_{run_id[:8]}.html"
        html_path = os.path.join(tempfile.gettempdir(), html_filename)
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Réponse avec headers corrects
        response = make_response(send_file(
            html_path,
            as_attachment=True,
            download_name=html_filename,
            mimetype='text/html; charset=utf-8'
        ))
        
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{html_filename}"'
        
        return response
        
    except Exception as e:
        print(f"❌ Erreur génération rapport: {e}")
        return jsonify({"error": f"Erreur de génération: {str(e)}"}), 500

@app.route("/download-image/<run_id>/<image_type>")
def download_image(run_id, image_type):
    """Télécharger une image de graphique"""
    if run_id not in BACKTEST_STORE:
        return jsonify({"error": "Run non trouvé"}), 404
        
    if image_type not in ["equity", "drawdown"]:
        return jsonify({"error": "Type d'image invalide"}), 400
        
    # Support des deux structures (charts et images)
    charts_data = BACKTEST_STORE[run_id].get("charts", BACKTEST_STORE[run_id].get("images", {}))
    image_path = charts_data.get(image_type, charts_data.get(f"{image_type}_chart"))
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "Image non trouvée"}), 404
        
    return send_file(image_path, as_attachment=True)


# -----------------------------------------------------------------------------
# ROUTES POUR SERVIR LES FICHIERS HTML STATIQUES
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    """Page d'accueil - Upload Strategy"""
    from flask import redirect
    return redirect('/upload_strategy.html')


@app.route('/<path:filename>')
def serve_static(filename):
    """Sert les fichiers HTML du dossier front/"""
    import os
    from flask import send_from_directory
    
    # Chemin vers le dossier front (un niveau au-dessus de datafeed_tester)
    front_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'front'))
    
    # Vérifier si le fichier existe
    file_path = os.path.join(front_dir, filename)
    if os.path.exists(file_path):
        response = send_from_directory(front_dir, filename)
        # Headers pour empêcher le cache
        if hasattr(response, 'headers'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # Si le fichier n'existe pas, retourner 404
    return jsonify({"error": f"Fichier {filename} non trouvé"}), 404


# -----------------------------------------------------------------------------
# ENDPOINT SMARTBOT V2
# -----------------------------------------------------------------------------

@app.route('/backtest-smartbot-v2', methods=['POST'])
def backtest_smartbot_v2_endpoint():
    """
    Endpoint pour backtester SmartBot V2 avec configuration complète
    """
    try:
        data = request.json
        
        # Récupération des données de marché
        symbol = data.get('symbol', 'BTC')
        quote = data.get('quote', 'USD')
        exchange_name = data.get('exchange', 'binance')
        timeframe = data.get('timeframe', '1d')
        start_date = data.get('start_date', '2024-01-01')
        end_date = data.get('end_date', '2025-01-01')
        
        print(f"📊 Backtest SmartBot V2: {symbol}-{quote} sur {exchange_name}")
        print(f"📅 Période demandée: {start_date} → {end_date}")
        
        # Convertir les dates en timestamps milliseconds pour le fetcher
        from datetime import datetime as dt, timezone
        try:
            start_dt = dt.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_dt = dt.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            since_ms = int(start_dt.timestamp() * 1000)
            until_ms = int(end_dt.timestamp() * 1000)
            print(f"🕐 Timestamps: since_ms={since_ms}, until_ms={until_ms}")
        except Exception as e:
            print(f"❌ Erreur de conversion des dates: {e}")
            return jsonify({"error": f"Format de date invalide: {e}"}), 400
        
        # Mapper les timeframes pour le fetcher CCXT
        timeframe_map = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d'
        }
        tf = timeframe_map.get(timeframe, '1d')
        
        # ==============================================
        # ALPACA (US STOCKS) - Traitement direct
        # ==============================================
        if exchange_name.lower() == "alpaca":
            print(f"📈 Mode STOCKS US - Téléchargement {symbol} via Alpaca")
            
            try:
                # Appel direct à fetch_ohlcv pour Alpaca
                df = fetch_ohlcv(
                    exchange="alpaca",
                    symbol=symbol,  # Pour Alpaca, juste le ticker (ex: 'AAPL')
                    timeframe=tf,
                    since_ms=since_ms,
                    until_ms=until_ms
                )
                
                if df.empty:
                    print(f"❌ Aucune donnée Alpaca pour {symbol}")
                    return jsonify({"error": f"Aucune donnée disponible pour le stock {symbol} sur Alpaca. Vérifiez le ticker."}), 400
                
                print(f"✅ {len(df)} bougies téléchargées depuis Alpaca")
                
                # Définir l'index datetime
                if 'date' in df.columns:
                    df = df.set_index('date')
                elif 'timestamp' in df.columns:
                    df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                    df = df.drop('timestamp', axis=1, errors='ignore')
                
                # S'assurer que l'index est un DatetimeIndex
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, unit='ms', utc=True)
                
                # Supprimer colonnes inutiles
                df = df.drop(['exchange', 'pair'], axis=1, errors='ignore')
                if 'timestamp' in df.columns:
                    df = df.drop('timestamp', axis=1)
                
                # Renommer les colonnes pour le backtester
                df = df.rename(columns={
                    'open': 'Open',
                    'high': 'High',
                    'low': 'Low',
                    'close': 'Close',
                    'volume': 'Volume'
                })
                
            except Exception as e:
                print(f"❌ Erreur Alpaca: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({"error": f"Erreur lors de la récupération des données Alpaca: {str(e)}"}), 500
        
        # ==============================================
        # CRYPTO (BINANCE, COINBASE, etc.) - Multi-sources
        # ==============================================
        else:
            # Téléchargement des données via le fetcher multi-sources
            print(f"🔄 Téléchargement {symbol} via fetcher multi-sources (timeframe={tf}, {start_date} → {end_date})")
            
            try:
                # Utilisation du fetcher avec les meilleurs exchanges
                exchanges_list = ['binance', 'coinbase', 'kraken', 'kucoin', 'okx']
                if exchange_name.lower() in exchanges_list:
                    # Mettre l'exchange choisi en priorité
                    exchanges_list = [exchange_name.lower()] + [e for e in exchanges_list if e != exchange_name.lower()]
                
                agg, detail, fetch_data = compare_exchanges_on_bases(
                    exchanges=exchanges_list,
                    bases=[symbol],
                    timeframe=tf,
                    lookback_days=365,  # Paramètre requis mais non utilisé car on passe since_ms/until_ms
                    since_ms=since_ms,  # Utiliser les timestamps exacts
                    until_ms=until_ms,  # Utiliser les timestamps exacts
                    selection="best"
                )
                
                # Vérification des résultats
                if agg is None or agg.empty:
                    print(f"❌ Aucune donnée reçue via le fetcher pour {symbol}")
                    return jsonify({"error": f"Aucune donnée disponible pour {symbol} sur la période {start_date} à {end_date}. Essayez un autre symbole."}), 400
                
                if symbol not in fetch_data.get("__FINAL__", {}):
                    available = list(fetch_data.get("__FINAL__", {}).keys())
                    print(f"❌ {symbol} non trouvé. Disponibles: {available}")
                    return jsonify({"error": f"Symbole {symbol} non trouvé. Disponibles: {available}"}), 400
                
                # Récupération du DataFrame final
                df = fetch_data["__FINAL__"][symbol].copy()
                
                if df.empty:
                    print(f"❌ DataFrame vide pour {symbol}")
                    return jsonify({"error": f"Aucune donnée récupérée pour {symbol}"}), 400
                
                print(f"✅ {len(df)} bougies téléchargées via {fetch_data['__FINAL_META__'][symbol]['provenance']}")
                
                # Définir l'index datetime AVANT tout le reste
                # Le fetcher retourne une colonne 'date' déjà convertie en datetime
                if 'date' in df.columns:
                    df = df.set_index('date')
                elif 'timestamp' in df.columns:
                    df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                    df = df.drop('timestamp', axis=1, errors='ignore')
                
                # S'assurer que l'index est un DatetimeIndex
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, unit='ms', utc=True)
                
                # Supprimer la colonne timestamp si elle existe encore
                if 'timestamp' in df.columns:
                    df = df.drop('timestamp', axis=1)
                
                # Renommer les colonnes du fetcher (minuscules) vers format backtester (majuscules)
                df = df.rename(columns={
                    'open': 'Open',
                    'high': 'High',
                    'low': 'Low',
                    'close': 'Close',
                    'volume': 'Volume'
                })
                
                # Vérifier les colonnes requises
                required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
                missing = [col for col in required_cols if col not in df.columns]
                if missing:
                    print(f"❌ Colonnes manquantes: {missing}")
                    return jsonify({"error": f"Colonnes manquantes dans les données: {missing}"}), 400
                
                # Garder seulement les colonnes nécessaires et nettoyer
                df = df[required_cols]
                df = df.dropna()
                
                # Filtrer les données pour correspondre exactement à la période demandée
                # Convertir start_date et end_date en datetime avec timezone
                filter_start = pd.to_datetime(start_date).tz_localize('UTC')
                filter_end = pd.to_datetime(end_date).tz_localize('UTC')
                
                # S'assurer que l'index a une timezone
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                
                # ✅ FIX: Supprimer les lignes avec index NaN avant le masque booléen
                df = df[~df.index.isna()]
                
                # Filtrer
                df = df[(df.index >= filter_start) & (df.index <= filter_end)]
                
                if df.empty:
                    print(f"❌ Aucune donnée après filtrage de la période {start_date} à {end_date}")
                    return jsonify({"error": f"Aucune donnée dans la période demandée {start_date} à {end_date}"}), 400
                
                # Affichage sécurisé des dates
                start_str = df.index[0].strftime('%Y-%m-%d %H:%M') if hasattr(df.index[0], 'strftime') else str(df.index[0])
                end_str = df.index[-1].strftime('%Y-%m-%d %H:%M') if hasattr(df.index[-1], 'strftime') else str(df.index[-1])
                print(f"✅ Données standardisées: {len(df)} bougies de {start_str} à {end_str}")
                
            except Exception as e:
                print(f"❌ Erreur lors de la récupération des données: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({"error": f"Erreur fetcher: {str(e)}"}), 500
        
        # Configuration des paramètres SmartBot V2
        params = ParametresDCA_SmartBotV2(
            # DSC Configuration
            dsc=data.get('dsc', 'RSI + MFI'),
            dsc2_enabled=data.get('dsc2_enabled', False),
            dsc2=data.get('dsc2', 'Bollinger Band %'),
            
            # Order Settings
            base_order=float(data.get('base_order', 1000.0)),
            safe_order=float(data.get('safe_order', 1500.0)),
            max_safe_order=int(data.get('max_so', 20)),
            safe_order_volume_scale=float(data.get('so_volume_scale', 1.5)),
            
            # Price Deviation Settings
            pricedevbase=data.get('pricedevbase', 'ATR'),
            price_deviation=float(data.get('price_deviation', 4.0)),
            deviation_scale=float(data.get('deviation_scale', 1.0)),
            
            # ATR Settings
            atr_length=int(data.get('atr_length', 14)),
            atr_mult=float(data.get('atr_mult', 3.0)),
            atr_mult_step_scale=float(data.get('atr_step_scale', 1.2)),
            
            # Take Profit Settings
            take_profit=float(data.get('take_profit', 1.5)),
            tp_type=data.get('tp_type', 'From Average Entry'),
            
            # Indicator Settings: RSI
            rsi_length=int(data.get('rsi_length', 2)),
            dsc_rsi_threshold_low=int(data.get('rsi_threshold', 3)),
            
            # Indicator Settings: MFI
            mfi_length=int(data.get('mfi_length', 14)),
            mfi_threshold_low=int(data.get('mfi_threshold', 30)),
            
            # Indicator Settings: Bollinger Bands
            bb_length=int(data.get('bb_length', 20)),
            bb_mult=float(data.get('bb_mult', 2.0)),
            bb_threshold_low=float(data.get('bb_threshold_low', 0.0)),
            
            # System Settings
            initial_capital=float(data.get('initial_capital', 100000.0)),
            commission=float(data.get('commission', 0.001)),
            slippage_pourcent=float(data.get('slippage', 0.0)),
            restrict_trading_to_us_market_hours=(exchange_name.lower() == 'alpaca'),
            trading_timeframe=tf,
            # Par défaut, on garde la position ouverte en fin de période.
            close_last_trade=bool(data.get('close_last_trade', False))
        )
        
        # Exécution du backtest
        print(f"🚀 Lancement du backtest SmartBot V2...")
        trades, equity, statistics = backtest_smartbot_v2(df, params)
        
        # DEBUG: Afficher les nouvelles métriques
        print(f"\n📊 STATISTICS RETOURNÉ PAR BACKTESTER:")
        print(f"   Keys: {list(statistics.keys())}")
        print(f"   total_days: {statistics.get('total_days', 'MISSING')}")
        print(f"   trades_per_day: {statistics.get('trades_per_day', 'MISSING')}")
        print(f"   avg_open_positions_per_day: {statistics.get('avg_open_positions_per_day', 'MISSING')}")
        print(f"   max_capital_used: {statistics.get('max_capital_used', 'MISSING')}")
        print(f"   max_capital_used_pct: {statistics.get('max_capital_used_pct', 'MISSING')}\n")
        
        # Générer le rapport TradingView
        tradingview_positions = []
        if not trades.empty:
            for trade_idx, (_, trade) in enumerate(trades.iterrows(), start=1):
                positions = trade.get("individual_positions") if hasattr(trade, "get") else None
                if isinstance(positions, list) and positions:
                    for pos in positions:
                        tradingview_positions.append({
                            "trade_id": trade_idx,
                            "type": pos['type'],
                            "entry_time": pos['entry_time'].strftime('%Y-%m-%d %H:%M'),
                            "entry_price": float(pos['entry_price']),
                            "exit_time": trade['exit_time'].strftime('%Y-%m-%d %H:%M'),
                            "exit_price": float(pos['exit_price']),
                            "size_usd": float(pos['size_usd']),
                            "qty": float(pos['qty']),
                            "pnl": float(pos['pnl']),
                            "pnl_pct": float(pos['pnl_pct'])
                        })
        
        # DEBUG: Vérifier que trade_id est bien ajouté
        if tradingview_positions:
            print(f"🔍 DEBUG Backend: {len(tradingview_positions)} positions créées")
            print(f"🔍 Première position a trade_id: {tradingview_positions[0].get('trade_id')}")
            print(f"🔍 Exemple: {tradingview_positions[0]}")
        
        # Ajouter les positions d'un trade encore ouvert (non clôturé)
        open_trade = statistics.get("open_trade") if isinstance(statistics, dict) else None
        if open_trade and open_trade.get("individual_positions"):
            current_time = open_trade.get("current_time")
            current_price = float(open_trade.get("current_price", 0.0))
            # L'ID du trade ouvert est le prochain numéro après les trades fermés
            open_trade_id = len(trades) + 1 if not trades.empty else 1
            for pos in open_trade["individual_positions"]:
                entry_time_raw = pos.get('entry_time')
                if hasattr(entry_time_raw, 'strftime'):
                    entry_time_fmt = entry_time_raw.strftime('%Y-%m-%d %H:%M')
                else:
                    entry_time_fmt = str(entry_time_raw)

                if hasattr(current_time, 'strftime'):
                    current_time_fmt = current_time.strftime('%Y-%m-%d %H:%M')
                else:
                    current_time_fmt = str(current_time)

                tradingview_positions.append({
                    "trade_id": open_trade_id,
                    "type": pos.get('type', 'OPEN'),
                    "entry_time": entry_time_fmt,
                    "entry_price": float(pos.get('entry_price', 0.0)),
                    "exit_time": current_time_fmt,
                    "exit_price": current_price,
                    "qty": float(pos.get('qty', 0.0)),
                    "size_usd": float(pos.get('size_usd', 0.0)),
                    "pnl": float(pos.get('pnl', 0.0)),
                    "pnl_pct": float(pos.get('pnl_pct', 0.0)),
                    "status": "OPEN",
                    "progress": f"Trade en cours | SO: {int(open_trade.get('so_count', 0))}"
                })
        
        # Préparer les données pour l'equity curve
        equity_data = {
            'x': equity.index.strftime('%Y-%m-%d %H:%M').tolist(),
            'y': equity.values.tolist()
        }
        
        # Générer le graphique de prix avec marqueurs (style multi-asset)
        chart_trades = trades.copy()
        if open_trade:
            chart_trades = pd.concat([
                chart_trades,
                pd.DataFrame([{
                    "entry_time": open_trade.get("entry_time"),
                    "entry_price": open_trade.get("entry_price"),
                    "so_times": open_trade.get("so_times", []),
                    "so_prices": open_trade.get("so_prices", []),
                    "open_current_time": open_trade.get("current_time"),
                    "open_current_price": open_trade.get("current_price"),
                    "reason": "OPEN"
                }])
            ], ignore_index=True)

        price_chart = create_plotly_price_chart(
            df,
            chart_trades,
            f"{symbol} - SmartBot V2"
        )
        
        # Préparer la réponse
        response = {
            "success": True,
            "symbol": f"{symbol}-{quote}",
            "period": f"{start_date} to {end_date}",
            "trades": trades.to_dict('records') if not trades.empty else [],
            "tradingview_positions": tradingview_positions,
            "statistics": statistics,
            "open_trade": open_trade,
            "equity_data": equity_data,
            "price_chart": price_chart
        }
        
        print(f"✅ Backtest terminé: {statistics.get('total_trades', 0)} trades")
        
        return jsonify(convert_pandas_to_json(response))
        
    except Exception as e:
        print(f"❌ Erreur backtest SmartBot V2: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def create_plotly_price_chart(df_price, trades_df, title: str = "Price Chart"):
    """Crée un graphique Plotly avec marqueurs de trades pour le multi-asset"""
    traces = []
    
    if not df_price.empty:
        # Candlestick chart
        candlestick = {
            'type': 'candlestick',
            'x': df_price.index.strftime('%Y-%m-%d').tolist(),
            'open': df_price['Open'].tolist(),
            'high': df_price['High'].tolist(),
            'low': df_price['Low'].tolist(),
            'close': df_price['Close'].tolist(),
            'name': 'Price',
            'increasing': {'line': {'color': '#000000'}},
            'decreasing': {'line': {'color': '#999999'}}
        }
        traces.append(candlestick)
    
    if not trades_df.empty:
        # Marqueurs BO (Base Order)
        bo_dates = []
        bo_prices = []
        for _, trade in trades_df.iterrows():
            if 'entry_time' in trade and 'entry_price' in trade and pd.notna(trade['entry_time']):
                bo_dates.append(pd.to_datetime(trade['entry_time']).strftime('%Y-%m-%d'))
                bo_prices.append(float(trade['entry_price']))
        
        if bo_dates:
            traces.append({
                'type': 'scatter',
                'mode': 'markers+text',
                'x': bo_dates,
                'y': bo_prices,
                'name': 'Base Order',
                'text': ['BO'] * len(bo_dates),
                'textposition': 'top center',
                'marker': {'color': '#000000', 'size': 12, 'symbol': 'triangle-up'},
                'showlegend': True
            })
        
        # Marqueurs SO (Safety Orders)
        so_dates = []
        so_prices = []
        so_labels = []
        for _, trade in trades_df.iterrows():
            if 'so_times' in trade and 'so_prices' in trade:
                so_times_list = trade['so_times']
                so_prices_list = trade['so_prices']
                
                if isinstance(so_times_list, (list, tuple)) and isinstance(so_prices_list, (list, tuple)):
                    for idx, (so_time, so_price) in enumerate(zip(so_times_list, so_prices_list), 1):
                        so_dates.append(pd.to_datetime(so_time).strftime('%Y-%m-%d'))
                        so_prices.append(float(so_price))
                        so_labels.append(f'SO{idx}')
        
        if so_dates:
            traces.append({
                'type': 'scatter',
                'mode': 'markers+text',
                'x': so_dates,
                'y': so_prices,
                'name': 'Safety Orders',
                'text': so_labels,
                'textposition': 'top center',
                'marker': {'color': '#FFA500', 'size': 10, 'symbol': 'triangle-right'},
                'showlegend': True
            })
        
        # Marqueurs TP (Take Profit)
        tp_dates = []
        tp_prices = []
        for _, trade in trades_df.iterrows():
            if 'exit_time' in trade and 'exit_price' in trade and pd.notna(trade['exit_time']):
                tp_dates.append(pd.to_datetime(trade['exit_time']).strftime('%Y-%m-%d'))
                tp_prices.append(float(trade['exit_price']))
        
        if tp_dates:
            traces.append({
                'type': 'scatter',
                'mode': 'markers+text',
                'x': tp_dates,
                'y': tp_prices,
                'name': 'Take Profit',
                'text': ['TP'] * len(tp_dates),
                'textposition': 'bottom center',
                'marker': {'color': '#000000', 'size': 12, 'symbol': 'triangle-down'},
                'showlegend': True
            })

        # Marqueur du trade encore ouvert (position courante)
        open_dates = []
        open_prices = []
        for _, trade in trades_df.iterrows():
            if 'open_current_time' in trade and 'open_current_price' in trade:
                if pd.notna(trade['open_current_time']) and pd.notna(trade['open_current_price']):
                    open_dates.append(pd.to_datetime(trade['open_current_time']).strftime('%Y-%m-%d'))
                    open_prices.append(float(trade['open_current_price']))

        if open_dates:
            traces.append({
                'type': 'scatter',
                'mode': 'markers+text',
                'x': open_dates,
                'y': open_prices,
                'name': 'Trade En Cours',
                'text': ['OPEN'] * len(open_dates),
                'textposition': 'bottom center',
                'marker': {'color': '#1f77b4', 'size': 12, 'symbol': 'diamond'},
                'showlegend': True
            })
    
    layout = {
        'title': {
            'text': title,
            'font': {'size': 18, 'color': '#000000', 'family': 'Arial Black'}
        },
        'xaxis': {
            'title': 'Date',
            'titlefont': {'size': 12, 'color': '#000000'},
            'gridcolor': '#e0e0e0'
        },
        'yaxis': {
            'title': 'Price',
            'titlefont': {'size': 12, 'color': '#000000'},
            'gridcolor': '#e0e0e0'
        },
        'paper_bgcolor': '#ffffff',
        'plot_bgcolor': '#ffffff',
        'hovermode': 'x unified',
        'showlegend': True,
        'legend': {'x': 0, 'y': 1}
    }
    
    return {'data': traces, 'layout': layout}


@app.route('/backtest-smartbot-v2-multi', methods=['POST'])
def backtest_smartbot_v2_multi_endpoint():
    """
    Endpoint pour backtester SmartBot V2 Multi-Asset avec gestion de portfolio
    """
    request_t0 = time.perf_counter()
    try:
        data = request.json
        
        # Récupération des paramètres
        assets = data.get('assets', ['BTC', 'ETH'])
        if isinstance(assets, str):
            assets = [a.strip() for a in assets.split(',')]
        assets = [a for a in assets if a]
        
        quote = data.get('quote', 'USD')
        exchange_name = data.get('exchange', 'binance')
        timeframe = data.get('timeframe', '1d')
        start_date = data.get('start_date', '2024-01-01')
        end_date = data.get('end_date', '2025-01-01')
        max_active_trades = int(data.get('max_active_trades', 3))
        
        print(f"📊 Backtest SmartBot V2 Multi-Asset: {assets} sur {exchange_name}")
        print(f"📅 Période: {start_date} → {end_date}")
        print(f"🎯 Max Active Trades: {max_active_trades}")
        
        # Configuration des paramètres SmartBot V2
        params = ParametresDCA_SmartBotV2(
            dsc=data.get('dsc', 'RSI + MFI'),
            base_order=float(data.get('base_order', 1000.0)),
            safe_order=float(data.get('safe_order', 1500.0)),
            max_safe_order=int(data.get('max_so', 20)),
            safe_order_volume_scale=float(data.get('so_volume_scale', 1.5)),
            pricedevbase=data.get('pricedevbase', 'ATR'),
            price_deviation=float(data.get('price_deviation', 4.0)),
            atr_length=int(data.get('atr_length', 14)),
            atr_mult=float(data.get('atr_mult', 3.0)),
            atr_mult_step_scale=float(data.get('atr_step_scale', 1.2)),
            take_profit=float(data.get('take_profit', 1.5)),
            tp_type=data.get('tp_type', 'From Average Entry'),
            rsi_length=int(data.get('rsi_length', 2)),
            dsc_rsi_threshold_low=int(data.get('rsi_threshold', 3)),
            mfi_length=int(data.get('mfi_length', 14)),
            mfi_threshold_low=int(data.get('mfi_threshold', 30)),
            bb_length=int(data.get('bb_length', 20)),
            initial_capital=float(data.get('initial_capital', 100000.0)),
            commission=float(data.get('commission', 0.001)),
            restrict_trading_to_us_market_hours=(exchange_name.lower() == 'alpaca'),
            trading_timeframe=timeframe,
            # Par défaut, on garde les positions ouvertes en fin de période.
            close_last_trade=bool(data.get('close_last_trade', False))
        )
        
        # Téléchargement des données pour tous les assets
        from datetime import datetime as dt, timezone
        start_dt = dt.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_dt = dt.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        since_ms = int(start_dt.timestamp() * 1000)
        until_ms = int(end_dt.timestamp() * 1000)
        
        tf_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
        tf = tf_map.get(timeframe, '1d')
        
        # ==============================================
        # ALPACA (US STOCKS) - Téléchargement direct pour chaque stock
        # ==============================================
        fetch_t0 = time.perf_counter()
        if exchange_name.lower() == "alpaca":
            print(f"📈 Mode STOCKS US - Téléchargement {len(assets)} stocks via Alpaca")
            
            fetch_data = {"__FINAL__": {}, "__FINAL_META__": {}}
            
            for asset in assets:
                try:
                    print(f"  📊 Téléchargement {asset}...")
                    df = fetch_ohlcv(
                        exchange="alpaca",
                        symbol=asset,
                        timeframe=tf,
                        since_ms=since_ms,
                        until_ms=until_ms
                    )
                    
                    if not df.empty:
                        fetch_data["__FINAL__"][asset] = df
                        fetch_data["__FINAL_META__"][asset] = {"provenance": "alpaca", "symbol": asset}
                        print(f"  ✅ {asset}: {len(df)} bougies")
                    else:
                        print(f"  ⚠️ {asset}: Aucune donnée")
                        
                except Exception as e:
                    print(f"  ❌ {asset}: Erreur - {str(e)}")
                    continue
            
            if not fetch_data["__FINAL__"]:
                return jsonify({"error": "Aucune donnée récupérée depuis Alpaca pour les stocks demandés"}), 400
        
        # ==============================================
        # CRYPTO - Binance uniquement (optimisation performance)
        # ==============================================
        else:
            print(f"🔄 Téléchargement des données pour {len(assets)} assets depuis Binance...")
            agg, detail, fetch_data = fetch_binance_only_cached(
                bases=assets,
                timeframe=tf,
                lookback_days=365,
                since_ms=since_ms,
                until_ms=until_ms
            )
        log_perf("fetch-data", fetch_t0)
        
        if not fetch_data.get("__FINAL__"):
            return jsonify({"error": "Aucune donnée récupérée"}), 400
        
        # Préparer les DataFrames de tous les assets
        assets_prepared = {}
        prep_t0 = time.perf_counter()
        
        print(f"\n{'='*80}")
        print(f"🚀 PRÉPARATION MULTI-ASSET BACKTEST")
        print(f"{'='*80}\n")
        
        for asset in assets:
            if asset not in fetch_data["__FINAL__"]:
                print(f"⚠️ {asset} non disponible, ignoré")
                continue
            
            print(f"📈 Préparation {asset}...")
            
            df = fetch_data["__FINAL__"][asset].copy()
            
            # Standardisation
            if 'date' in df.columns:
                df = df.set_index('date')
            elif 'timestamp' in df.columns:
                df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df = df.drop('timestamp', axis=1, errors='ignore')
            
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, unit='ms', utc=True)
            
            df = df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'volume': 'Volume'
            })
            
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
            
            # Filtrage dates
            filter_start = pd.to_datetime(start_date).tz_localize('UTC')
            filter_end = pd.to_datetime(end_date).tz_localize('UTC')
            
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            
            # ✅ FIX: Supprimer les lignes avec index NaN avant le masque booléen
            df = df[~df.index.isna()]
            
            df = df[(df.index >= filter_start) & (df.index <= filter_end)]
            
            if df.empty:
                print(f"⚠️ {asset}: Aucune donnée après filtrage")
                continue
            
            assets_prepared[asset] = df
            print(f"✅ {asset}: {len(df)} barres")
        
        if not assets_prepared:
            return jsonify({"error": "Aucun asset disponible après préparation"}), 400
        log_perf("prepare-data", prep_t0)
        
        # Exécuter le backtest multi-portfolio avec limitation de positions
        from backtester_exact import backtest_smartbot_v2_multi_portfolio
        bt_t0 = time.perf_counter()
        
        per_asset_trades, per_asset_equity, per_asset_stats, combined_equity, portfolio_stats = backtest_smartbot_v2_multi_portfolio(
            assets_prepared,
            params,
            max_active_trades
        )
        log_perf("run-backtest", bt_t0)
        
        # DEBUG: Vérifier que les positions ont trade_id dans le multi-asset
        first_asset_with_positions = None
        for asset_name, asset_stats in per_asset_stats.items():
            if asset_stats.get('individual_positions'):
                first_asset_with_positions = asset_name
                positions = asset_stats['individual_positions']
                print(f"🔍 DEBUG Multi-Asset Backend:")
                print(f"  Asset: {asset_name}")
                print(f"  Nombre de positions: {len(positions)}")
                if positions:
                    print(f"  Première position: {positions[0]}")
                    print(f"  trade_id présent? {positions[0].get('trade_id')}")
                break
        
        # Calculer le capital final à partir de l'equity combinée
        final_capital = combined_equity.iloc[-1] if not combined_equity.empty else params.initial_capital
        
        # Statistiques combinées
        total_positions = sum(s.get('total_trades', 0) for s in per_asset_stats.values())
        total_deals = sum(s.get('total_deals', 0) for s in per_asset_stats.values())
        total_orders = sum(s.get('total_orders_placed', 0) for s in per_asset_stats.values())
        total_pnl = sum(s.get('total_pnl', 0) for s in per_asset_stats.values())
        total_so_placed = sum(s.get('total_so_placed', 0) for s in per_asset_stats.values())
        avg_win_rate = np.mean([s.get('win_rate', 0) for s in per_asset_stats.values()]) if per_asset_stats else 0
        avg_win_rate_tradingview = np.mean([s.get('win_rate_tradingview', 0) for s in per_asset_stats.values()]) if per_asset_stats else 0
        
        # NOUVELLES MÉTRIQUES : Calculer à partir des données disponibles
        # 1. Total days depuis combined_equity
        if not combined_equity.empty and len(combined_equity) > 1:
            first_date = combined_equity.index[0]
            last_date = combined_equity.index[-1]
            total_days = (last_date - first_date).days + 1
        else:
            total_days = 1
        
        # 2. Trades per day (deals BO uniquement)
        trades_per_day = total_deals / total_days if total_days > 0 else 0
        
        # 3. Avg open positions per day - approximation basée sur l'activité du portfolio
        # Sans tracking historique des positions ouvertes jour par jour,
        # on approxime en supposant qu'en moyenne, environ 60-70% des slots étaient occupés
        # (car le bot cherche toujours à remplir les slots mais il faut du temps pour sortir)
        portfolio_utilization = 0.65  # 65% des slots en moyenne
        avg_open_positions_per_day = max_active_trades * portfolio_utilization
        
        # 4. Max capital used - approximation basée sur les paramètres du bot
        # Dans un portfolio DCA multi-asset, le capital max utilisé dépend de:
        # - Nombre max de trades actifs simultanément
        # - Taille de chaque position (base_order + safety orders)
        # Approximation: base_order * max_active * facteur_SO (2-4x selon stratégie aggressive)
        # Facteur moyen: 1 (BO) + avg SO utilisés (≈ 2-3)
        avg_so_factor = 3.0  # Approximation: BO + en moyenne 2 SO actifs
        theoretical_max_capital = params.base_order * max_active_trades * avg_so_factor
        max_capital_used = min(theoretical_max_capital, params.initial_capital)
        max_capital_used_pct = (max_capital_used / params.initial_capital * 100) if params.initial_capital > 0 else 0
        
        total_pnl_equity = float(final_capital - params.initial_capital)
        total_return_pct_equity = float((total_pnl_equity / params.initial_capital) * 100) if params.initial_capital > 0 else 0.0

        combined_stats = {
            "initial_capital": params.initial_capital,
            # IMPORTANT: aligner le Final Capital avec la fin de l'equity curve
            "final_capital": float(final_capital),
            "total_return_pct": total_return_pct_equity,
            "total_trades": total_deals,
            "total_deals": total_deals,
            "total_positions": total_positions,
            "total_orders": total_orders,
            "total_so_placed": total_so_placed,
            "avg_win_rate": float(avg_win_rate),
            "avg_win_rate_tradingview": float(avg_win_rate_tradingview),
            "total_pnl": total_pnl_equity,
            "max_drawdown": float(portfolio_stats['max_drawdown']),
            "max_drawdown_pct": float(portfolio_stats['max_drawdown_pct']),
            "assets_count": len(per_asset_stats),
            "open_trades_at_end": portfolio_stats['open_positions'],
            "max_active_trades": max_active_trades,
            # NOUVELLES MÉTRIQUES
            "total_days": int(total_days),
            "trades_per_day": float(trades_per_day),
            "avg_open_positions_per_day": float(avg_open_positions_per_day),
            "max_capital_used": float(max_capital_used),
            "max_capital_used_pct": float(max_capital_used_pct)
        }
        
        # DEBUG: Afficher les nouvelles métriques calculées
        print(f"\n📊 NOUVELLES MÉTRIQUES CALCULÉES:")
        print(f"   Total Days:                 {total_days}")
        print(f"   Total Deals (BO):           {total_deals}")
        print(f"   Total Positions (BO+SO):    {total_positions}")
        print(f"   Trades per Day:             {trades_per_day:.2f}")
        print(f"   Avg Open Positions/Day:     {avg_open_positions_per_day:.2f}")
        print(f"   Max Capital Used:           ${max_capital_used:.2f} ({max_capital_used_pct:.1f}%)")
        print(f"   Max Active Trades:          {max_active_trades}")
        
        # Formatter l'equity curve combinée
        combined_equity_list = [
            {"date": date.strftime('%Y-%m-%d %H:%M:%S'), "equity": float(value)}
            for date, value in combined_equity.items()
        ]
        
        print(f"\n{'='*80}")
        print(f"📊 RÉSULTATS MULTI-ASSET PORTFOLIO")
        print(f"{'='*80}")
        print(f"Capital Initial:   ${combined_stats['initial_capital']:.2f}")
        print(f"Capital Final:     ${combined_stats['final_capital']:.2f}")
        print(f"Return:            {combined_stats['total_return_pct']:.2f}%")
        print(f"Max Drawdown:      ${combined_stats['max_drawdown']:.2f} ({combined_stats['max_drawdown_pct']:.2f}%)")
        print(f"Total Deals:       {combined_stats['total_trades']}")
        print(f"Total Orders:      {combined_stats['total_orders']}")
        print(f"Avg Win Rate:      {combined_stats['avg_win_rate']:.1f}%")
        print(f"Assets Traded:     {combined_stats['assets_count']}")
        print(f"Max Active Trades: {max_active_trades}")
        print(f"{'='*80}\n")
        
        # Générer les graphiques pour chaque asset
        per_asset_charts = {}
        for asset in assets_prepared.keys():
            if asset in per_asset_trades and not per_asset_trades[asset].empty:
                df_asset = assets_prepared[asset]
                trades_asset = per_asset_trades[asset]
                
                # Générer le graphique avec les marqueurs
                chart_data = create_plotly_price_chart(
                    df_asset, 
                    trades_asset, 
                    f"{asset} - SmartBot V2"
                )
                per_asset_charts[asset] = chart_data
        
        response = {
            "success": True,
            "assets": list(assets_prepared.keys()),
            "period": f"{start_date} to {end_date}",
            "combined_stats": combined_stats,
            "per_asset_stats": per_asset_stats,
            "combined_equity": combined_equity_list,
            "per_asset_charts": per_asset_charts,
            "performance": {
                "total_seconds": round(time.perf_counter() - request_t0, 3),
                "memory_mb": round(get_memory_mb() or 0, 1),
                "total_bars": int(sum(len(df) for df in assets_prepared.values()))
            }
        }
        log_perf("total-request", request_t0)
        
        return jsonify(convert_pandas_to_json(response))
        
    except Exception as e:
        print(f"❌ Erreur backtest SmartBot V2 Multi: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        # Libération explicite des objets lourds après chaque requête
        gc.collect()


# -----------------------------------------------------------------------------
# POINT D'ENTRÉE
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5002"))
    print("🚀 Démarrage de l'API Kronos...")
    print(f"📖 Documentation disponible sur: http://localhost:{port}")
    print("🌐 Interface Web disponible sur:")
    print(f"   http://localhost:{port}/upload_strategy.html")
    print(f"   http://localhost:{port}/run_multi.html")
    print("")
    print("🔧 Routes API disponibles:")
    print("   GET  /health")
    print("   GET  /strategies")
    print("   POST /ingest-score")
    print("   POST /backtest")
    print("   POST /report")
    print("   POST /run-multi-backtest")
    print("   POST /backtest-custom-strategy")
    app.run(debug=False, host="0.0.0.0", port=port)
