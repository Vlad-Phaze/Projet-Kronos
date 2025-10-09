import React, { useState } from 'react';
import './App.css';
import ConfigPanel from './components/ConfigPanel';
import MainDashboard from './components/MainDashboard';
import StatusPanel from './components/StatusPanel';
import { BacktestConfig, BacktestResult } from './types';

const App: React.FC = () => {
  const [config, setConfig] = useState<BacktestConfig>({
    // Paramètres Fetcheur
    coin: 'BTC',
    exchanges: ['binance', 'coinbase', 'kraken', 'kucoin'],
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    
    // Paramètres Stratégie DCA
    rsiLength: 14,
    rsiEntry: 30,
    rsiExit: 75,
    bbLength: 20,
    bbStd: 3,
    bbpTrigger: 0.2,
    minTp: 0.01,
    soMax: 4,
    soStep: 0.0021,
    soVolumeScale: 1,
    soStepScale: 1,
    direction: 'long',
    useMfi: false,
    useMacd: false,
    useEma: false,
    
    // Paramètres Backtester
    initialCapital: 10000,
    commission: 0.0005,
    
    // Code de stratégie personnalisé
    strategyCode: `def ma_strategie(df, params):
    rsi = ta.rsi(df['close'], length=params.get('rsi_length', 14))
    signals = pd.DataFrame(index=df.index)
    signals['side'] = np.where(rsi < params.get('rsi_entry', 30), 'long', 'flat')
    return signals`
  });

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  const addLog = (message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    setLogs((prev: string[]) => [...prev.slice(-19), `[${timestamp}] ${message}`]);
  };

  const runBacktest = async () => {
    setIsLoading(true);
    addLog('🚀 Démarrage du backtest...');
    
    try {
      addLog('📊 Configuration des paramètres...');
      addLog(`💰 Capital initial: ${config.initialCapital}$`);
      addLog(`🪙 Crypto: ${config.coin}`);
      
      // Simulation d'API call
      const response = await fetch('http://localhost:5002/backtest', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          symbol: `${config.coin}-USD`,
          start_date: config.startDate,
          end_date: config.endDate,
          strategy_code: config.strategyCode,
          params: {
            rsi_length: config.rsiLength,
            rsi_entry: config.rsiEntry,
            rsi_exit: config.rsiExit,
            bb_length: config.bbLength,
            bb_std: config.bbStd,
            bbp_trigger: config.bbpTrigger,
            min_tp: config.minTp,
            so_max: config.soMax,
            so_step: config.soStep,
            so_volume_scale: config.soVolumeScale,
            so_step_scale: config.soStepScale,
            direction: config.direction,
            quantite_base: config.initialCapital,
            commission: config.commission
          }
        })
      });

      if (response.ok) {
        const data = await response.json();
        setResult(data);
        addLog('✅ Backtest terminé avec succès!');
        addLog(`📈 Nombre de trades: ${data.trades_count || 'N/A'}`);
        addLog(`💵 PnL final: ${data.total_return || 'N/A'}%`);
      } else {
        addLog('❌ Erreur lors du backtest');
      }
    } catch (error) {
      addLog('❌ Erreur de connexion à l\'API');
      console.error('Erreur:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const downloadReport = async () => {
    if (!result?.report_id) return;
    
    addLog('📄 Génération du rapport HTML...');
    try {
      const response = await fetch(`http://localhost:5002/download-report/${result.report_id}`);
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `rapport_kronos_${result.report_id}.html`;
        a.click();
        addLog('✅ Rapport téléchargé!');
      }
    } catch (error) {
      addLog('❌ Erreur lors du téléchargement');
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="logo">KRONOS BACKTESTER</div>
        <div className="status-indicator">
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            API Status
          </span>
          <div className="status-dot"></div>
          <span style={{ color: 'var(--text-accent)', fontSize: '0.9rem' }}>
            ONLINE
          </span>
        </div>
      </header>

      <ConfigPanel 
        config={config} 
        setConfig={setConfig}
        onRunBacktest={runBacktest}
        isLoading={isLoading}
      />

      <MainDashboard 
        result={result}
        isLoading={isLoading}
        onDownloadReport={downloadReport}
      />

      <StatusPanel logs={logs} />
    </div>
  );
};

export default App;
