#!/bin/bash
# Script de nettoyage avant push GitHub

echo "🧹 Nettoyage du projet Kronos avant push GitHub..."

cd "$(dirname "$0")"

# Racine
echo "📁 Nettoyage racine..."
rm -f api_simple.py backtester.py backtester_exact.py compare_strategies.py
rm -f dca_library_backtestingpy.py demo_rapport.py launch_api_corrected.py
rm -f restart_services.sh strategy_dca_adapted.py advanced_metrics.py
rm -f exchange_coverage_report.csv flask_server.log kronos
rm -f test_exchange_coverage.py
rm -rf __pycache__/

# datafeed_tester
echo "📁 Nettoyage datafeed_tester..."
cd datafeed_tester
rm -f app_corrected.py app_new.py backtester_exact.py backtester_perfect.py
rm -f backtester_tradingview_exact.py backtester_tradingview_real.py
rm -f download_app.py run_flask.py
rm -f analyze_missed_dates.py analyze_new_csv_forensic.py compare_results.py
rm -f detective_tradingview.py detective_tradingview_phase2.py validate_final_results.py
rm -f cmc_headless_scrape.py find_common_cryptos.py gather_exchange_open_interest.py
rm -f generate_cmc_intersection.py generate_cross_exchange.py generate_csv.py
rm -f get_all_cryptos.py get_all_pairs_volume.py
rm -f pair_vol_mcap_coingecko.py pair_vol_mcap_coingecko_by_coinpage.py
rm -f scrape_cmc_all.py scrape_cmc_for_pairs.py
rm -f run_btc_2025_vectorbt.py run_btc_2025_vectorbt_direct.py
rm -f multi_vectorbt_*.csv vectorbt_*.csv
rm -f DCAStrategy.html .DS_Store
rm -rf __pycache__/ strategies/__pycache__/ core/__pycache__/

cd ..

# front
echo "📁 Nettoyage front..."
cd front
rm -f kronos-client.html
rm -rf react-app/

cd ..

# Fichiers macOS
echo "🍎 Suppression fichiers macOS..."
find . -name ".DS_Store" -delete

echo "✅ Nettoyage terminé!"
echo ""
echo "📋 Fichiers essentiels conservés:"
echo "   - README.md, STRATEGY_GUIDE.md, STRATEGY_QUICKSTART.md"
echo "   - restart_server.sh"
echo "   - datafeed_tester/ (app.py, fetcher.py, backtester_vectorbt.py, etc.)"
echo "   - datafeed_tester/core/"
echo "   - datafeed_tester/strategies/"
echo "   - front/upload_strategy.html"
echo ""
echo "🚀 Vous pouvez maintenant faire:"
echo "   git add ."
echo "   git commit -m 'Clean: Suppression fichiers obsolètes'"
echo "   git push"
