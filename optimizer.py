#!/usr/bin/env python3
"""
SmartBot V2 - Système d'Optimisation Automatique des Paramètres
===============================================================

Ce module permet de tester automatiquement différentes valeurs de paramètres
pour trouver la meilleure configuration de stratégie basée sur les critères choisis.

Fonctionnalités:
- Optimisation d'un seul paramètre (range scan)
- Optimisation de plusieurs paramètres (grid search)
- Critères multiples: gain total, drawdown, ratio gain/drawdown
- Export des résultats en JSON/CSV
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict, replace
from typing import Dict, List, Any, Optional, Tuple, Union
from itertools import product
import time
from datetime import datetime
import json

# Import du backtester
from backtester_exact import (
    ParametresDCA_SmartBotV2,
    backtest_smartbot_v2,
)


@dataclass
class ParameterRange:
    """Définit une plage de valeurs pour un paramètre à optimiser"""
    name: str  # Nom du paramètre (ex: "rsi_length")
    min_value: Union[int, float]  # Valeur minimale
    max_value: Union[int, float]  # Valeur maximale
    step: Union[int, float] = 1  # Pas d'incrémentation
    type: str = "int"  # Type: "int" ou "float"
    
    def get_values(self) -> List[Union[int, float]]:
        """Génère la liste des valeurs à tester"""
        if self.type == "int":
            return list(range(int(self.min_value), int(self.max_value) + 1, int(self.step)))
        else:
            values = []
            current = self.min_value
            while current <= self.max_value:
                values.append(round(current, 4))
                current += self.step
            return values


@dataclass
class OptimizationResult:
    """Résultat d'un backtest avec une configuration spécifique"""
    parameters: Dict[str, Any]  # Paramètres testés
    total_pnl: float  # Gain total
    max_drawdown_pct: float  # Drawdown maximum (%)
    gain_drawdown_ratio: float  # Ratio gain/drawdown
    final_capital: float  # Capital final
    capital_return_pct: float  # Rendement (%)
    total_trades: int  # Nombre de trades
    win_rate: float  # Taux de réussite (%)
    avg_pnl_per_trade: float  # PnL moyen par trade
    max_so_used: int  # Nombre max de SO utilisés
    trades_per_day: float  # Trades par jour
    max_capital_used_pct: float  # Capital max utilisé (%)
    execution_time: float  # Temps d'exécution (secondes)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire"""
        return {
            **self.parameters,
            "total_pnl": self.total_pnl,
            "max_drawdown_pct": self.max_drawdown_pct,
            "gain_drawdown_ratio": self.gain_drawdown_ratio,
            "final_capital": self.final_capital,
            "capital_return_pct": self.capital_return_pct,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "avg_pnl_per_trade": self.avg_pnl_per_trade,
            "max_so_used": self.max_so_used,
            "trades_per_day": self.trades_per_day,
            "max_capital_used_pct": self.max_capital_used_pct,
            "execution_time": self.execution_time,
        }


class StrategyOptimizer:
    """
    Optimiseur de stratégie SmartBot V2
    
    Permet de tester automatiquement différentes combinaisons de paramètres
    pour trouver la configuration optimale selon les critères choisis.
    """
    
    def __init__(self, price_data: pd.DataFrame, base_params: ParametresDCA_SmartBotV2):
        """
        Initialise l'optimiseur
        
        Args:
            price_data: DataFrame avec les données de prix (OHLCV)
            base_params: Paramètres de base de la stratégie (non optimisés)
        """
        self.price_data = price_data
        self.base_params = base_params
        self.results: List[OptimizationResult] = []
        
    def run_single_parameter_optimization(
        self,
        param_range: ParameterRange,
        progress_callback: Optional[callable] = None
    ) -> List[OptimizationResult]:
        """
        Optimise un seul paramètre
        
        Args:
            param_range: Plage de valeurs pour le paramètre
            progress_callback: Fonction de callback pour la progression (optionnel)
                              Signature: callback(current, total, message)
        
        Returns:
            Liste des résultats triés par gain/drawdown ratio
        """
        values = param_range.get_values()
        total_iterations = len(values)
        
        print(f"\n{'='*70}")
        print(f"🔍 OPTIMISATION DE '{param_range.name}'")
        print(f"{'='*70}")
        print(f"Plage: {param_range.min_value} à {param_range.max_value} (step={param_range.step})")
        print(f"Nombre de tests: {total_iterations}")
        print(f"{'='*70}\n")
        
        self.results = []
        
        for idx, value in enumerate(values, 1):
            start_time = time.time()
            
            # Créer les paramètres avec la nouvelle valeur
            test_params = replace(self.base_params, **{param_range.name: value})
            
            # Exécuter le backtest
            try:
                trades, equity, stats = backtest_smartbot_v2(self.price_data, test_params)
                execution_time = time.time() - start_time
                
                # Calculer le ratio gain/drawdown
                # Si drawdown = 0, ratio = gain total (pas de risque pris)
                if abs(stats["max_drawdown_pct"]) > 0.01:
                    gain_dd_ratio = stats["capital_return_pct"] / abs(stats["max_drawdown_pct"])
                else:
                    gain_dd_ratio = stats["capital_return_pct"] * 100  # Bonus si pas de drawdown
                
                # Créer le résultat
                result = OptimizationResult(
                    parameters={param_range.name: value},
                    total_pnl=stats["total_pnl"],
                    max_drawdown_pct=stats["max_drawdown_pct"],
                    gain_drawdown_ratio=gain_dd_ratio,
                    final_capital=stats["final_capital"],
                    capital_return_pct=stats["capital_return_pct"],
                    total_trades=stats["total_trades"],
                    win_rate=stats["win_rate_tradingview"],
                    avg_pnl_per_trade=stats.get("avg_pnl_per_trade", 0.0),
                    max_so_used=stats["max_so_used"],
                    trades_per_day=stats.get("trades_per_day", 0.0),
                    max_capital_used_pct=stats.get("max_capital_used_pct", 0.0),
                    execution_time=execution_time,
                )
                
                self.results.append(result)
                
                # Callback de progression
                if progress_callback:
                    progress_callback(
                        idx,
                        total_iterations,
                        f"{param_range.name}={value} | PnL=${result.total_pnl:.2f} | DD={result.max_drawdown_pct:.2f}%"
                    )
                
                # Affichage console
                print(f"[{idx}/{total_iterations}] {param_range.name}={value:>6} | "
                      f"PnL: ${result.total_pnl:>10.2f} | "
                      f"DD: {result.max_drawdown_pct:>6.2f}% | "
                      f"Ratio: {result.gain_drawdown_ratio:>6.2f} | "
                      f"({execution_time:.2f}s)")
                
            except Exception as e:
                print(f"❌ Erreur pour {param_range.name}={value}: {e}")
                if progress_callback:
                    progress_callback(idx, total_iterations, f"Erreur: {str(e)}")
        
        # Trier par ratio gain/drawdown
        self.results.sort(key=lambda x: x.gain_drawdown_ratio, reverse=True)
        
        print(f"\n{'='*70}")
        print(f"✅ Optimisation terminée! {len(self.results)} configurations testées")
        print(f"{'='*70}\n")
        
        return self.results
    
    def run_grid_search(
        self,
        param_ranges: List[ParameterRange],
        max_iterations: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> List[OptimizationResult]:
        """
        Optimise plusieurs paramètres simultanément (grid search)
        
        Args:
            param_ranges: Liste des plages de paramètres à optimiser
            max_iterations: Nombre maximum d'itérations (optionnel, pour limiter le temps)
            progress_callback: Fonction de callback pour la progression
        
        Returns:
            Liste des résultats triés par gain/drawdown ratio
        """
        # Générer toutes les combinaisons possibles
        param_values = [pr.get_values() for pr in param_ranges]
        all_combinations = list(product(*param_values))
        
        # Limiter le nombre d'itérations si nécessaire
        if max_iterations and len(all_combinations) > max_iterations:
            print(f"⚠️ Limitation du nombre de combinaisons: {len(all_combinations)} → {max_iterations}")
            import random
            random.shuffle(all_combinations)
            all_combinations = all_combinations[:max_iterations]
        
        total_iterations = len(all_combinations)
        
        print(f"\n{'='*70}")
        print(f"🔍 GRID SEARCH - OPTIMISATION MULTI-PARAMÈTRES")
        print(f"{'='*70}")
        print(f"Paramètres à optimiser:")
        for pr in param_ranges:
            print(f"  - {pr.name}: {pr.min_value} à {pr.max_value} (step={pr.step}) → {len(pr.get_values())} valeurs")
        print(f"Nombre total de combinaisons: {total_iterations}")
        print(f"{'='*70}\n")
        
        self.results = []
        
        for idx, combination in enumerate(all_combinations, 1):
            start_time = time.time()
            
            # Créer le dictionnaire de paramètres
            params_dict = {pr.name: val for pr, val in zip(param_ranges, combination)}
            
            # Créer les paramètres avec les nouvelles valeurs
            test_params = replace(self.base_params, **params_dict)
            
            # Exécuter le backtest
            try:
                trades, equity, stats = backtest_smartbot_v2(self.price_data, test_params)
                execution_time = time.time() - start_time
                
                # Calculer le ratio gain/drawdown
                if abs(stats["max_drawdown_pct"]) > 0.01:
                    gain_dd_ratio = stats["capital_return_pct"] / abs(stats["max_drawdown_pct"])
                else:
                    gain_dd_ratio = stats["capital_return_pct"] * 100
                
                # Créer le résultat
                result = OptimizationResult(
                    parameters=params_dict,
                    total_pnl=stats["total_pnl"],
                    max_drawdown_pct=stats["max_drawdown_pct"],
                    gain_drawdown_ratio=gain_dd_ratio,
                    final_capital=stats["final_capital"],
                    capital_return_pct=stats["capital_return_pct"],
                    total_trades=stats["total_trades"],
                    win_rate=stats["win_rate_tradingview"],
                    avg_pnl_per_trade=stats.get("avg_pnl_per_trade", 0.0),
                    max_so_used=stats["max_so_used"],
                    trades_per_day=stats.get("trades_per_day", 0.0),
                    max_capital_used_pct=stats.get("max_capital_used_pct", 0.0),
                    execution_time=execution_time,
                )
                
                self.results.append(result)
                
                # Callback de progression
                if progress_callback:
                    params_str = ", ".join([f"{k}={v}" for k, v in params_dict.items()])
                    progress_callback(
                        idx,
                        total_iterations,
                        f"{params_str} | PnL=${result.total_pnl:.2f} | Ratio={result.gain_drawdown_ratio:.2f}"
                    )
                
                # Affichage console (plus compact pour grid search)
                params_str = ", ".join([f"{k}={v}" for k, v in params_dict.items()])
                print(f"[{idx}/{total_iterations}] {params_str:<40} | "
                      f"PnL: ${result.total_pnl:>8.0f} | "
                      f"Ratio: {result.gain_drawdown_ratio:>6.2f} | "
                      f"({execution_time:.1f}s)")
                
            except Exception as e:
                print(f"❌ Erreur pour {params_dict}: {e}")
                if progress_callback:
                    progress_callback(idx, total_iterations, f"Erreur: {str(e)}")
        
        # Trier par ratio gain/drawdown
        self.results.sort(key=lambda x: x.gain_drawdown_ratio, reverse=True)
        
        print(f"\n{'='*70}")
        print(f"✅ Grid Search terminée! {len(self.results)} configurations testées")
        print(f"{'='*70}\n")
        
        return self.results
    
    def get_top_results(self, n: int = 10, sort_by: str = "gain_drawdown_ratio") -> List[OptimizationResult]:
        """
        Retourne les N meilleurs résultats
        
        Args:
            n: Nombre de résultats à retourner
            sort_by: Critère de tri ("gain_drawdown_ratio", "total_pnl", "max_drawdown_pct")
        
        Returns:
            Liste des N meilleurs résultats
        """
        if sort_by == "gain_drawdown_ratio":
            sorted_results = sorted(self.results, key=lambda x: x.gain_drawdown_ratio, reverse=True)
        elif sort_by == "total_pnl":
            sorted_results = sorted(self.results, key=lambda x: x.total_pnl, reverse=True)
        elif sort_by == "max_drawdown_pct":
            sorted_results = sorted(self.results, key=lambda x: abs(x.max_drawdown_pct))
        elif sort_by == "capital_return_pct":
            sorted_results = sorted(self.results, key=lambda x: x.capital_return_pct, reverse=True)
        else:
            sorted_results = self.results
        
        return sorted_results[:n]
    
    def export_results_to_csv(self, filepath: str):
        """Exporte les résultats en CSV"""
        if not self.results:
            print("❌ Aucun résultat à exporter")
            return
        
        df = pd.DataFrame([r.to_dict() for r in self.results])
        df.to_csv(filepath, index=False)
        print(f"✅ Résultats exportés vers: {filepath}")
    
    def export_results_to_json(self, filepath: str):
        """Exporte les résultats en JSON"""
        if not self.results:
            print("❌ Aucun résultat à exporter")
            return
        
        data = {
            "optimization_date": datetime.now().isoformat(),
            "total_configurations": len(self.results),
            "base_parameters": asdict(self.base_params),
            "results": [r.to_dict() for r in self.results]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Résultats exportés vers: {filepath}")
    
    def print_summary(self, top_n: int = 5):
        """Affiche un résumé des meilleurs résultats"""
        if not self.results:
            print("❌ Aucun résultat disponible")
            return
        
        top_results = self.get_top_results(top_n)
        
        print(f"\n{'='*100}")
        print(f"🏆 TOP {top_n} DES MEILLEURES CONFIGURATIONS")
        print(f"{'='*100}\n")
        
        for idx, result in enumerate(top_results, 1):
            print(f"#{idx} - {result.parameters}")
            print(f"    💰 PnL Total: ${result.total_pnl:,.2f} ({result.capital_return_pct:+.2f}%)")
            print(f"    📉 Drawdown Max: {result.max_drawdown_pct:.2f}%")
            print(f"    📊 Ratio Gain/DD: {result.gain_drawdown_ratio:.2f}")
            print(f"    🎯 Win Rate: {result.win_rate:.1f}%")
            print(f"    📈 Trades: {result.total_trades} ({result.trades_per_day:.2f}/jour)")
            print(f"    💼 Capital Max Utilisé: {result.max_capital_used_pct:.1f}%")
            print(f"    ⏱️  Temps: {result.execution_time:.2f}s")
            print()


# ═══════════════════════════════════════════════════════════
# EXEMPLE D'UTILISATION
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import yfinance as yf
    
    print("📥 Téléchargement des données de test...")
    ticker = yf.Ticker("BTC-USD")
    prix = ticker.history(period="1y", interval="1d")
    
    if prix.empty:
        print("❌ Erreur: impossible de télécharger les données")
        exit(1)
    
    print(f"✅ {len(prix)} barres téléchargées ({prix.index[0]} à {prix.index[-1]})")
    
    # Paramètres de base
    params_base = ParametresDCA_SmartBotV2(
        # DSC
        dsc="RSI",
        dsc2_enabled=False,
        
        # Orders
        base_order=1000.0,
        safe_order=1500.0,
        max_safe_order=10,
        safe_order_volume_scale=1.5,
        
        # Price Deviation
        pricedevbase="ATR",
        price_deviation=4.0,
        atr_length=14,
        atr_mult=3.0,
        
        # Take Profit
        take_profit=1.5,
        tp_type="From Average Entry",
        
        # Indicators (seront optimisés)
        rsi_length=2,
        rsi_source="close",
        dsc_rsi_threshold_low=3,
        
        # System
        initial_capital=100000.0,
        commission=0.001,
    )
    
    # Créer l'optimiseur
    optimizer = StrategyOptimizer(prix, params_base)
    
    # EXEMPLE 1: Optimiser un seul paramètre (RSI length)
    print("\n" + "="*70)
    print("EXEMPLE 1: Optimisation simple (RSI length)")
    print("="*70)
    
    rsi_range = ParameterRange(
        name="rsi_length",
        min_value=2,
        max_value=10,
        step=1,
        type="int"
    )
    
    results = optimizer.run_single_parameter_optimization(rsi_range)
    optimizer.print_summary(top_n=3)
    
    # EXEMPLE 2: Grid search (RSI + MFI)
    print("\n" + "="*70)
    print("EXEMPLE 2: Grid Search (RSI length + RSI threshold)")
    print("="*70)
    
    ranges = [
        ParameterRange("rsi_length", 2, 6, 1, "int"),
        ParameterRange("dsc_rsi_threshold_low", 1, 5, 1, "int"),
    ]
    
    results = optimizer.run_grid_search(ranges)
    optimizer.print_summary(top_n=5)
    
    # Export des résultats
    optimizer.export_results_to_csv("optimization_results.csv")
    optimizer.export_results_to_json("optimization_results.json")
