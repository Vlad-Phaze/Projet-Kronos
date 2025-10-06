# core/fetcher_adapter.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import pandas as pd

# ⚠️ On importe TON fetcher tel quel.
#    Assure-toi que ton fichier s'appelle bien `fetcher.py` à la racine du projet
#    (ou adapte l'import ci-dessous si besoin).
from datafeed_tester.fetcher import (
    EXCHANGES,
    expand_coin_inputs,
    compare_exchanges_on_bases,
)

def fetch_market_data(
    bases: List[str],
    timeframe: str,
    lookback_days: int,
    exchanges: List[str] | None = None,
    selection: str = "best",
    fixed_exchange: str | None = None,
    preferred_quotes=("USDT", "USD", "USDC", "EUR", "BTC"),
    allowed_exchanges: List[str] | None = None,
    include_derivatives: bool = False,
    use_group_expansion: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any], list[dict], pd.DataFrame, pd.DataFrame]:
    """
    Facade simple autour de ton fetcher:
      - expansion de groupes (optionnelle) : "Large Cap", "Stable coins", etc.
      - appel à compare_exchanges_on_bases(...)
      - extraction des résultats utiles pour l’orchestrateur

    Retourne:
      - data_final: {base_symbol: DataFrame OHLCV}
      - meta_final: {base_symbol: meta (provenance / mode / score...)}
      - errors:     liste d’erreurs structurées (prêtes pour un front)
      - agg:        DataFrame agrégé des scores moyens par exchange
      - detail:     DataFrame détaillé des métriques par exchange/base
    """
    exchanges = exchanges or EXCHANGES

    # 1) (Optionnel) expansion des mots-clés groupes via CoinGecko
    front_errors: list[dict] = []
    if use_group_expansion:
        bases = expand_coin_inputs(bases, errors=front_errors)

    # 2) Appel à ton cœur de fetch
    agg, detail, data = compare_exchanges_on_bases(
        exchanges,
        bases,
        timeframe,
        lookback_days,
        preferred_quotes=preferred_quotes,
        allowed_exchanges=allowed_exchanges,
        selection=selection,
        fixed_exchange=fixed_exchange,
        include_derivatives=include_derivatives,
    )

    # 3) Extraction des sorties finales
    data_final: dict[str, pd.DataFrame] = data.get("__FINAL__", {})
    meta_final: dict[str, Any] = data.get("__FINAL_META__", {})
    errors: list[dict] = data.get("__ERRORS__", [])
    # concatène les erreurs issues de l’expansion (si activée)
    errors.extend(front_errors)

    return data_final, meta_final, errors, agg, detail
