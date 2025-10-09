export interface BacktestConfig {
  // Paramètres Fetcheur
  coin: string;
  exchanges: string[];
  startDate: string;
  endDate: string;
  
  // Paramètres Stratégie DCA
  rsiLength: number;
  rsiEntry: number;
  rsiExit: number;
  bbLength: number;
  bbStd: number;
  bbpTrigger: number;
  minTp: number;
  soMax: number;
  soStep: number;
  soVolumeScale: number;
  soStepScale: number;
  direction: 'long' | 'short';
  useMfi: boolean;
  useMacd: boolean;
  useEma: boolean;
  
  // Paramètres Backtester
  initialCapital: number;
  commission: number;
  
  // Code stratégie
  strategyCode: string;
}

export interface BacktestResult {
  report_id: string;
  total_return: number;
  trades_count: number;
  win_rate: number;
  max_drawdown: number;
  sharpe_ratio: number;
  equity_data: Array<{
    timestamp: string;
    value: number;
  }>;
  trades_data: Array<{
    entry_time: string;
    exit_time: string;
    entry_price: number;
    exit_price: number;
    pnl: number;
    side: string;
  }>;
}
