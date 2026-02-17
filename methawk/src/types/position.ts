export type PositionStatus = 'active' | 'closed' | 'failed';

export interface ManagedPosition {
  id?: number;
  pool_address: string;
  pool_name: string;
  position_pubkey: string;
  token_x_symbol: string;
  token_y_symbol: string;
  token_x_address: string;
  token_y_address: string;
  strategy_name: string;
  bins: number;
  distribution: string;
  rebalance_direction: string;
  rebalance_cooldown_min: number;
  entry_time: string;
  entry_sol: number;
  entry_bin_id: number;
  lower_bin_id: number;
  upper_bin_id: number;
  safety_score: number;
  opportunity_score: number;
  status: PositionStatus;
  exit_time?: string;
  exit_sol?: number;
  fees_earned_sol?: number;
  fees_earned_usd?: number;
  pnl_sol?: number;
  pnl_percent?: number;
  exit_reason?: string;
  rebalance_count: number;
  last_rebalance_time?: string;
  paper_trade: boolean;
  entry_price?: number;
  current_price?: number;
  current_bin_id?: number;
  stop_loss_percent?: number;
  take_profit_percent?: number;
  max_hold_minutes?: number;
}

export interface RebalanceRecord {
  id?: number;
  position_id: number;
  timestamp: string;
  direction: 'up' | 'down';
  old_lower_bin: number;
  old_upper_bin: number;
  new_lower_bin: number;
  new_upper_bin: number;
  old_active_bin: number;
  new_active_bin: number;
  fees_claimed_x: number;
  fees_claimed_y: number;
  tx_signature?: string;
}
