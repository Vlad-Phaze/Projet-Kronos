import React from 'react';
import { BacktestResult } from '../types';

interface MainDashboardProps {
  result: BacktestResult | null;
  isLoading: boolean;
  onDownloadReport: () => void;
}

const MainDashboard: React.FC<MainDashboardProps> = ({ result, isLoading, onDownloadReport }) => {
  if (isLoading) {
    return (
      <div className="main">
        <div className="loading">
          <div className="spinner"></div>
          <span style={{ marginLeft: '1rem' }}>Exécution du backtest...</span>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="main">
        <div className="chart-container" style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          flexDirection: 'column',
          textAlign: 'center'
        }}>
          <h2 style={{ color: 'var(--text-accent)', marginBottom: '1rem' }}>
            🚀 Prêt pour le Backtest
          </h2>
          <p style={{ color: 'var(--text-secondary)' }}>
            Configurez vos paramètres dans le panneau de gauche et lancez votre premier backtest.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="main">
      <div className="main-grid">
        {/* Métriques principales */}
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-value" style={{ 
              color: result.total_return >= 0 ? 'var(--text-accent)' : 'var(--accent-orange)' 
            }}>
              {result.total_return?.toFixed(2) || 'N/A'}%
            </div>
            <div className="metric-label">Rendement Total</div>
          </div>

          <div className="metric-card">
            <div className="metric-value">{result.trades_count || 0}</div>
            <div className="metric-label">Nombre de Trades</div>
          </div>

          <div className="metric-card">
            <div className="metric-value">
              {result.win_rate ? `${(result.win_rate * 100).toFixed(1)}%` : 'N/A'}
            </div>
            <div className="metric-label">Taux de Réussite</div>
          </div>

          <div className="metric-card">
            <div className="metric-value" style={{ color: 'var(--accent-orange)' }}>
              {result.max_drawdown ? `${(result.max_drawdown * 100).toFixed(2)}%` : 'N/A'}
            </div>
            <div className="metric-label">Drawdown Max</div>
          </div>

          <div className="metric-card">
            <div className="metric-value">
              {result.sharpe_ratio?.toFixed(2) || 'N/A'}
            </div>
            <div className="metric-label">Ratio de Sharpe</div>
          </div>
        </div>

        {/* Zone graphique */}
        <div className="chart-container">
          <h3 style={{ 
            color: 'var(--text-accent)', 
            marginBottom: '1rem',
            borderBottom: '1px solid var(--border-primary)',
            paddingBottom: '0.5rem'
          }}>
            📈 Courbe d'Équité
          </h3>
          
          {result.equity_data && result.equity_data.length > 0 ? (
            <div style={{ 
              width: '100%', 
              height: '300px', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center',
              color: 'var(--text-secondary)'
            }}>
              <p>Graphique d'équité (à implémenter avec Recharts)</p>
            </div>
          ) : (
            <div style={{ 
              width: '100%', 
              height: '300px', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center',
              color: 'var(--text-secondary)'
            }}>
              Aucune donnée d'équité disponible
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ 
          gridColumn: '1 / -1',
          display: 'flex',
          gap: '1rem',
          justifyContent: 'center'
        }}>
          <button
            className="btn-primary"
            onClick={onDownloadReport}
            style={{ width: 'auto', padding: '0.75rem 2rem' }}
          >
            📄 Télécharger Rapport HTML
          </button>
        </div>
      </div>
    </div>
  );
};

export default MainDashboard;
