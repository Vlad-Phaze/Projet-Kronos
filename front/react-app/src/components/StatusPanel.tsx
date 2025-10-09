import React from 'react';

interface StatusPanelProps {
  logs: string[];
}

const StatusPanel: React.FC<StatusPanelProps> = ({ logs }) => {
  return (
    <div className="status-panel">
      <div className="section">
        <h3 className="section-title">📊 État du Système</h3>
        
        <div className="metric-card" style={{ marginBottom: '1rem' }}>
          <div className="metric-value" style={{ fontSize: '1.2rem' }}>
            ONLINE
          </div>
          <div className="metric-label">API Status</div>
        </div>

        <div className="metric-card" style={{ marginBottom: '1rem' }}>
          <div className="metric-value" style={{ fontSize: '1.2rem' }}>
            {logs.length}
          </div>
          <div className="metric-label">Messages</div>
        </div>
      </div>

      <div className="section">
        <h3 className="section-title">📝 Journal d'Activité</h3>
        <div className="activity-log">
          {logs.length === 0 ? (
            <div className="log-entry" style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
              Aucune activité pour le moment...
            </div>
          ) : (
            logs.map((log, index) => (
              <div key={index} className="log-entry">
                {log}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="section">
        <h3 className="section-title">⚡ Performances</h3>
        <div style={{ 
          display: 'grid', 
          gap: '0.5rem',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>CPU:</span>
            <span style={{ color: 'var(--text-accent)' }}>12%</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>RAM:</span>
            <span style={{ color: 'var(--text-accent)' }}>256MB</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Latence:</span>
            <span style={{ color: 'var(--text-accent)' }}>45ms</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default StatusPanel;
