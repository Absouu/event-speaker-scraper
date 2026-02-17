export interface StrategyPreset {
  name: string;
  bins: number;
  distribution: 'spot' | 'bidAsk' | 'curve';
  rebalanceDirection: 'up_only' | 'down_only' | 'bothways';
  rebalanceCooldownMin: number;
  swapless: boolean;
  pingPong: boolean;
  autoCompound: boolean;
  autoAccumulateSOL: boolean;
  stopLoss: boolean;
  singleSidedSOL: boolean;
  action: 'enter' | 'skip';
  takeProfitPercent?: number;
  stopLossPercent?: number;
  maxHoldMinutes?: number;
}

export interface MarketCondition {
  volatilityLevel: 'low' | 'high' | 'very_high';
  volumeLevel: 'low' | 'high' | 'very_high';
  tokenCategory: 'major' | 'altcoin' | 'memecoin' | 'new_launch';
  priceTrend: 'uptrend' | 'sideways' | 'downtrend';
}

export const SKIP_PRESET: StrategyPreset = {
  name: 'SKIP',
  bins: 0,
  distribution: 'spot',
  rebalanceDirection: 'bothways',
  rebalanceCooldownMin: 0,
  swapless: true,
  pingPong: false,
  autoCompound: false,
  autoAccumulateSOL: false,
  stopLoss: false,
  singleSidedSOL: false,
  action: 'skip',
};
