import dotenv from 'dotenv';
import path from 'path';
import { AppConfig, BudgetConfig, PreEntryFilters } from './types/config';

dotenv.config({ path: path.resolve(__dirname, '../.env') });

export const CONFIG: AppConfig = {
  SOLANA_PRIVATE_KEY: process.env.WALLET_PRIVATE_KEY || process.env.SOLANA_PRIVATE_KEY || '',
  SOLANA_RPC_URL: process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com',
  HAWKFI_API_URL: 'https://api2.hawksight.co',
  BIRDEYE_API_KEY: process.env.BIRDEYE_API_KEY || '',
  RUGCHECK_API_KEY: process.env.RUGCHECK_API_KEY || '',
  PAPER_TRADE_MODE: process.env.PAPER_TRADE_MODE !== 'false',
  PRIORITY_FEE_LAMPORTS: 75000,
  COMMITMENT: 'confirmed',
  SCAN_INTERVAL_MS: 15 * 60 * 1000,      // 15 min pool discovery
  POLL_INTERVAL_MS: 30 * 1000,            // 30s position monitoring
  REBALANCE_COOLDOWN_MS: 5 * 60 * 1000,   // 5 min between rebalances
};

export const BUDGET: BudgetConfig = {
  GAS_RESERVE_SOL: 0.2,
  PER_POSITION_SOL: 0.4,
  MAX_POSITIONS: 3,
  MAX_TOTAL_DEPLOYED_SOL: 1.4,
  MAX_DAILY_LOSS_PERCENT: 10,
  STOP_LOSS_PERCENT: 20,
  TAKE_PROFIT_PERCENT: 50,
  DEFAULT_BINS: 23,
  DEFAULT_SLIPPAGE_BPS: 50,
  MIN_SAFETY_SCORE: 80,
  MIN_OPPORTUNITY_SCORE: 50,
  DEFAULT_AR_DIRECTION: 'up_only',
  AUTO_COMPOUND: false,
};

export const PRE_ENTRY: PreEntryFilters = {
  MIN_VOLUME_30M: 0,                // > 0 required (hard gate: dead pool filter)
  MIN_YIELD_OVER_TVL_30M: 0.001,    // Hard gate: pool actively generating fees
  MIN_VOLUME_DECAY_RATIO: 0.3,      // volume30m*48 / volume24h > 0.3 (soft: not decaying too fast)
  MIN_ORGANIC_SCORE: 0.7,           // Hard gate: volume is real (0-1 scale, ~7/10)
  MIN_TVL_USD: 2_000,               // Hard gate: enough depth for routing (lowered for fresh memecoins)
  MAX_PRICE_DIVERGENCE_PCT: 15,     // Hard gate: pool price vs Jupiter market (already in executor)
};

export const MAJOR_TOKENS = [
  'SOL', 'USDC', 'USDT', 'BTC', 'ETH', 'JLP', 'JITOSOL', 'MSOL', 'BSOL',
  'WBTC', 'WETH', 'RAY', 'JTO', 'PYTH', 'W', 'BONK',
];
