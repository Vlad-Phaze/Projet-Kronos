import React from 'react';
import { BacktestConfig } from '../types';

interface ConfigPanelProps {
  config: BacktestConfig;
  setConfig: React.Dispatch<React.SetStateAction<BacktestConfig>>;
  onRunBacktest: () => void;
  isLoading: boolean;
}

const ConfigPanel: React.FC<ConfigPanelProps> = ({ config, setConfig, onRunBacktest, isLoading }) => {
  const updateConfig = (key: keyof BacktestConfig, value: any) => {
    setConfig((prev: BacktestConfig) => ({ ...prev, [key]: value }));
  };

  const updateExchanges = (exchange: string, checked: boolean) => {
    setConfig((prev: BacktestConfig) => ({
      ...prev,
      exchanges: checked 
        ? [...prev.exchanges, exchange]
        : prev.exchanges.filter((e: string) => e !== exchange)
    }));
  };

  return (
    <div className="sidebar">
      {/* Section Fetcheur */}
      <div className="section">
        <h3 className="section-title">📊 Paramètres Fetcheur</h3>
        
        <div className="input-group">
          <label className="label">Cryptomonnaie</label>
          <select 
            className="select"
            value={config.coin}
            onChange={(e) => updateConfig('coin', e.target.value)}
          >
            <option value="BTC">Bitcoin (BTC)</option>
            <option value="ETH">Ethereum (ETH)</option>
            <option value="ADA">Cardano (ADA)</option>
            <option value="SOL">Solana (SOL)</option>
            <option value="MATIC">Polygon (MATIC)</option>
          </select>
        </div>

        <div className="input-group">
          <label className="label">Exchanges</label>
          {['binance', 'coinbase', 'kraken', 'kucoin'].map(exchange => (
            <div key={exchange} className="checkbox-group">
              <input
                type="checkbox"
                className="checkbox"
                checked={config.exchanges.includes(exchange)}
                onChange={(e) => updateExchanges(exchange, e.target.checked)}
              />
              <span style={{ textTransform: 'capitalize' }}>{exchange}</span>
            </div>
          ))}
        </div>

        <div className="input-group">
          <label className="label">Date de début</label>
          <input
            type="date"
            className="input"
            value={config.startDate}
            onChange={(e) => updateConfig('startDate', e.target.value)}
          />
        </div>

        <div className="input-group">
          <label className="label">Date de fin</label>
          <input
            type="date"
            className="input"
            value={config.endDate}
            onChange={(e) => updateConfig('endDate', e.target.value)}
          />
        </div>
      </div>

      {/* Section Stratégie DCA */}
      <div className="section">
        <h3 className="section-title">🎯 Stratégie DCA</h3>
        
        <div className="input-group">
          <label className="label">RSI Length</label>
          <input
            type="number"
            className="input"
            value={config.rsiLength}
            onChange={(e) => updateConfig('rsiLength', parseInt(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">RSI Entry</label>
          <input
            type="number"
            className="input"
            value={config.rsiEntry}
            onChange={(e) => updateConfig('rsiEntry', parseInt(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">RSI Exit</label>
          <input
            type="number"
            className="input"
            value={config.rsiExit}
            onChange={(e) => updateConfig('rsiExit', parseInt(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">Take Profit Min (%)</label>
          <input
            type="number"
            step="0.001"
            className="input"
            value={config.minTp}
            onChange={(e) => updateConfig('minTp', parseFloat(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">Safety Orders Max</label>
          <input
            type="number"
            className="input"
            value={config.soMax}
            onChange={(e) => updateConfig('soMax', parseInt(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">SO Step (%)</label>
          <input
            type="number"
            step="0.0001"
            className="input"
            value={config.soStep}
            onChange={(e) => updateConfig('soStep', parseFloat(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">Direction</label>
          <select 
            className="select"
            value={config.direction}
            onChange={(e) => updateConfig('direction', e.target.value)}
          >
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </div>
      </div>

      {/* Section Backtester */}
      <div className="section">
        <h3 className="section-title">💰 Backtester</h3>
        
        <div className="input-group">
          <label className="label">Capital Initial ($)</label>
          <input
            type="number"
            className="input"
            value={config.initialCapital}
            onChange={(e) => updateConfig('initialCapital', parseInt(e.target.value))}
          />
        </div>

        <div className="input-group">
          <label className="label">Commission (%)</label>
          <input
            type="number"
            step="0.0001"
            className="input"
            value={config.commission}
            onChange={(e) => updateConfig('commission', parseFloat(e.target.value))}
          />
        </div>
      </div>

      {/* Section Code Stratégie */}
      <div className="section">
        <h3 className="section-title">🔧 Code Stratégie</h3>
        <div className="input-group">
          <label className="label">Code Python personnalisé</label>
          <textarea
            className="input"
            rows={10}
            value={config.strategyCode}
            onChange={(e) => updateConfig('strategyCode', e.target.value)}
            style={{ 
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: '0.8rem',
              resize: 'vertical'
            }}
          />
        </div>
      </div>

      {/* Bouton de lancement */}
      <button
        className="btn-primary"
        onClick={onRunBacktest}
        disabled={isLoading}
      >
        {isLoading ? '🔄 Exécution...' : '🚀 Lancer Backtest'}
      </button>
    </div>
  );
};

export default ConfigPanel;
