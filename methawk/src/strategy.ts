/**
 * MetHawk Strategy Selector
 * Maps market conditions to DLMM strategy presets.
 * Adapted from CLAUDIA - maps distribution types to Meteora StrategyType.
 */

import { StrategyPreset, MarketCondition, SKIP_PRESET } from './types/strategy';
import { EnrichedPool } from './types/pool';
import { logger } from './utils/logger';

export interface StrategyDecision {
  preset: StrategyPreset;
  conditions: MarketCondition;
  binRange: { lower: number; upper: number };
  reason: string;
  confidence: 'high' | 'medium' | 'low';
}

const PRESETS: Record<string, StrategyPreset> = {
  HFL_SNIPER: {
    name: 'HFL_SNIPER', bins: 6, distribution: 'spot',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 0,
    swapless: true, pingPong: true, autoCompound: false,
    autoAccumulateSOL: true, stopLoss: true, singleSidedSOL: true, action: 'enter',
    takeProfitPercent: 5, stopLossPercent: 8, maxHoldMinutes: 120,
  },
  HFL_WIDE_BIDASK: {
    name: 'HFL_WIDE_BIDASK', bins: 18, distribution: 'bidAsk',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 30,
    swapless: true, pingPong: true, autoCompound: true,
    autoAccumulateSOL: false, stopLoss: false, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 15, stopLossPercent: 15,
  },
  HFL_TIGHT_SPOT: {
    name: 'HFL_TIGHT_SPOT', bins: 6, distribution: 'spot',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 0,
    swapless: true, pingPong: true, autoCompound: true,
    autoAccumulateSOL: false, stopLoss: false, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 15, stopLossPercent: 15,
  },
  HFL_TIGHT_CAUTIOUS: {
    name: 'HFL_TIGHT_CAUTIOUS', bins: 12, distribution: 'spot',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 10,
    swapless: true, pingPong: true, autoCompound: false,
    autoAccumulateSOL: true, stopLoss: true, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 15, stopLossPercent: 15,
  },
  HFL_WIDE_CAUTIOUS: {
    name: 'HFL_WIDE_CAUTIOUS', bins: 18, distribution: 'bidAsk',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 30,
    swapless: true, pingPong: true, autoCompound: false,
    autoAccumulateSOL: true, stopLoss: true, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 15, stopLossPercent: 15,
  },
  HFL_MEME_TIGHT: {
    name: 'HFL_MEME_TIGHT', bins: 6, distribution: 'spot',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 0,
    swapless: true, pingPong: true, autoCompound: true,
    autoAccumulateSOL: true, stopLoss: true, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 12, stopLossPercent: 10, maxHoldMinutes: 360,
  },
  HFL_MEME_WIDE: {
    name: 'HFL_MEME_WIDE', bins: 18, distribution: 'bidAsk',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 30,
    swapless: true, pingPong: true, autoCompound: true,
    autoAccumulateSOL: true, stopLoss: true, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 12, stopLossPercent: 10, maxHoldMinutes: 360,
  },
  HFL_MEME_CAUTIOUS: {
    name: 'HFL_MEME_CAUTIOUS', bins: 12, distribution: 'spot',
    rebalanceDirection: 'bothways', rebalanceCooldownMin: 10,
    swapless: true, pingPong: true, autoCompound: false,
    autoAccumulateSOL: true, stopLoss: false, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 12, stopLossPercent: 10, maxHoldMinutes: 360,
  },
  HFL_ALT: {
    name: 'HFL_ALT', bins: 12, distribution: 'spot',
    rebalanceDirection: 'up_only', rebalanceCooldownMin: 10,
    swapless: true, pingPong: true, autoCompound: true,
    autoAccumulateSOL: false, stopLoss: true, singleSidedSOL: false, action: 'enter',
    takeProfitPercent: 10, stopLossPercent: 12, maxHoldMinutes: 480,
  },
};

/**
 * Map our distribution type to Meteora DLMM StrategyType enum value
 * Spot=0, Curve=1, BidAsk=2
 */
export function toMeteorStrategyType(dist: 'spot' | 'bidAsk' | 'curve'): number {
  switch (dist) {
    case 'spot': return 0;
    case 'curve': return 1;
    case 'bidAsk': return 2;
  }
}

function extractConditions(pool: EnrichedPool): MarketCondition {
  return {
    volatilityLevel: pool.volatilityLevel,
    volumeLevel: pool.volumeLevel,
    tokenCategory: pool.tokenCategory,
    priceTrend: pool.priceTrend,
  };
}

function selectBaseStrategy(conditions: MarketCondition): { preset: StrategyPreset; reason: string } {
  const { volatilityLevel: vol, volumeLevel: volume, tokenCategory: category, priceTrend: trend } = conditions;

  if (trend === 'downtrend') {
    return { preset: { ...SKIP_PRESET }, reason: 'Downtrend detected -- avoid LPing' };
  }

  // New launches
  if (category === 'new_launch' && (volume === 'very_high' || volume === 'high')) {
    return { preset: { ...PRESETS.HFL_SNIPER }, reason: 'New launch with high volume -- HFL Sniper' };
  }
  if (category === 'new_launch') {
    return { preset: { ...SKIP_PRESET }, reason: 'New launch but volume too low -- skip' };
  }

  // Majors
  if (category === 'major') {
    if ((vol === 'high' || vol === 'very_high') && (volume === 'high' || volume === 'very_high')) {
      return { preset: { ...PRESETS.HFL_WIDE_BIDASK }, reason: 'Major: high vol + high volume -- wide bid-ask' };
    }
    if (vol === 'low' && (volume === 'high' || volume === 'very_high')) {
      return { preset: { ...PRESETS.HFL_TIGHT_SPOT }, reason: 'Major: SWEET SPOT -- low vol + high volume' };
    }
    if (vol === 'low' && volume === 'low') {
      return { preset: { ...PRESETS.HFL_TIGHT_CAUTIOUS }, reason: 'Major: low vol + low volume -- cautious' };
    }
    if ((vol === 'high' || vol === 'very_high') && volume === 'low') {
      return { preset: { ...PRESETS.HFL_WIDE_CAUTIOUS }, reason: 'Major: high vol + low volume -- wide cautious' };
    }
  }

  // Memecoins
  if (category === 'memecoin') {
    if ((vol === 'high' || vol === 'very_high') && volume === 'low') {
      return { preset: { ...SKIP_PRESET }, reason: 'Memecoin: high vol + low volume -- AVOID' };
    }
    if (vol === 'low' && (volume === 'high' || volume === 'very_high')) {
      return { preset: { ...PRESETS.HFL_MEME_TIGHT }, reason: 'Memecoin: low vol + high volume -- tight spot' };
    }
    if ((vol === 'high' || vol === 'very_high') && (volume === 'high' || volume === 'very_high')) {
      return { preset: { ...PRESETS.HFL_MEME_WIDE }, reason: 'Memecoin: high vol + high volume -- wide bid-ask' };
    }
    if (vol === 'low' && volume === 'low') {
      return { preset: { ...PRESETS.HFL_MEME_CAUTIOUS }, reason: 'Memecoin: low vol + low volume -- cautious' };
    }
  }

  // Altcoins
  if (category === 'altcoin') {
    if (volume === 'high' || volume === 'very_high') {
      const preset = { ...PRESETS.HFL_ALT };
      preset.distribution = (vol === 'high' || vol === 'very_high') ? 'bidAsk' : 'spot';
      return { preset, reason: `Altcoin: ${volume} volume -- HFL with up_only` };
    }
    if (volume === 'low' && vol === 'low') {
      return { preset: { ...PRESETS.HFL_MEME_CAUTIOUS, name: 'HFL_ALT_CAUTIOUS', takeProfitPercent: 10, stopLossPercent: 12, maxHoldMinutes: 480 }, reason: 'Altcoin: cautious' };
    }
    if (volume === 'low') {
      return { preset: { ...SKIP_PRESET }, reason: 'Altcoin: high vol + low volume -- skip' };
    }
  }

  return { preset: { ...SKIP_PRESET }, reason: `No strategy for ${category}/${vol}/${volume}/${trend}` };
}

function applyILMitigation(strategy: StrategyPreset, pool: EnrichedPool): StrategyPreset {
  const s = { ...strategy };
  if (s.action === 'skip') return s;

  if (pool.volatilityLevel === 'high' || pool.volatilityLevel === 'very_high') {
    s.bins = Math.min(s.bins * 2, 18);
  }
  if (pool.volatilityLevel === 'very_high' && s.rebalanceCooldownMin === 0) {
    s.rebalanceCooldownMin = 10;
  }
  if (pool.tokenCategory === 'major' && pool.priceTrend === 'uptrend') {
    s.rebalanceDirection = 'up_only';
  }
  if (pool.volatilityLevel !== 'low') {
    s.stopLoss = true;
  }
  return s;
}

function calculateBinRange(pool: EnrichedPool, baseBins: number): { lower: number; upper: number } {
  if (baseBins === 0) return { lower: 0, upper: 0 };

  const priceSwing4h = Math.abs(pool.priceChange4h || 0);
  const expectedDailySwing = priceSwing4h * 2;
  const binStepPct = (pool.binStep || 1) / 100;

  if (binStepPct > 0 && expectedDailySwing > 0) {
    const halfSwingBins = Math.ceil((expectedDailySwing / 2) / binStepPct);
    const adjustedBins = Math.max(baseBins, halfSwingBins);
    return { lower: -adjustedBins, upper: adjustedBins };
  }

  return { lower: -baseBins, upper: baseBins };
}

function determineConfidence(pool: EnrichedPool, conditions: MarketCondition, preset: StrategyPreset): 'high' | 'medium' | 'low' {
  if (preset.action === 'skip') return 'high';
  let score = 0;
  if (pool.priceChange1h !== 0 || pool.priceChange4h !== 0) score += 2;
  if (pool.poolAgeDays >= 0) score += 1;
  if (pool.holderCount > 0) score += 1;
  if (pool.hawkVolume1h > 0) score += 1;
  if (conditions.volatilityLevel === 'low' && conditions.volumeLevel === 'high') score += 2;
  if (pool.volumeTrend === 'increasing') score += 1;
  if (pool.hawkOrganicScore > 0.5) score += 1;
  if (score >= 6) return 'high';
  if (score >= 3) return 'medium';
  return 'low';
}

export function selectStrategy(pool: EnrichedPool): StrategyDecision {
  const conditions = extractConditions(pool);
  const { preset: basePreset, reason } = selectBaseStrategy(conditions);
  const mitigatedPreset = applyILMitigation(basePreset, pool);
  const binRange = calculateBinRange(pool, mitigatedPreset.bins);
  const confidence = determineConfidence(pool, conditions, mitigatedPreset);
  return { preset: mitigatedPreset, conditions, binRange, reason, confidence };
}

export function selectStrategiesForPools(pools: EnrichedPool[]): Array<{ pool: EnrichedPool; decision: StrategyDecision }> {
  const results = pools.map(pool => ({ pool, decision: selectStrategy(pool) }));
  results.sort((a, b) => {
    if (a.decision.preset.action !== b.decision.preset.action) {
      return a.decision.preset.action === 'enter' ? -1 : 1;
    }
    const confOrder = { high: 3, medium: 2, low: 1 };
    const confDiff = confOrder[b.decision.confidence] - confOrder[a.decision.confidence];
    if (confDiff !== 0) return confDiff;
    return b.pool.feeTvlRatio - a.pool.feeTvlRatio;
  });
  return results;
}

export function displayStrategyDecisions(results: Array<{ pool: EnrichedPool; decision: StrategyDecision }>): void {
  logger.separator('STRATEGY', 'STRATEGY SELECTION RESULTS');
  const headers = ['#', 'Pool', 'Strategy', 'Action', 'Bins', 'Dist', 'Rebal', 'SL', 'TP%', 'SL%', 'MaxH', 'Conf', 'Category', 'Reason'];
  const rows = results.map((r, i) => [
    String(i + 1),
    (r.pool.name || '?').substring(0, 14),
    r.decision.preset.name.substring(0, 16),
    r.decision.preset.action,
    String(r.decision.preset.bins),
    r.decision.preset.distribution.substring(0, 5),
    r.decision.preset.rebalanceDirection.substring(0, 7),
    r.decision.preset.stopLoss ? 'Y' : 'N',
    r.decision.preset.takeProfitPercent != null ? String(r.decision.preset.takeProfitPercent) : '-',
    r.decision.preset.stopLossPercent != null ? String(r.decision.preset.stopLossPercent) : '-',
    r.decision.preset.maxHoldMinutes != null ? `${r.decision.preset.maxHoldMinutes}m` : '-',
    r.decision.confidence.substring(0, 3),
    r.decision.conditions.tokenCategory.substring(0, 8),
    r.decision.reason.substring(0, 40),
  ]);
  logger.table('STRATEGY', headers, rows);

  const entering = results.filter(r => r.decision.preset.action === 'enter');
  const skipping = results.filter(r => r.decision.preset.action === 'skip');
  console.log(`\n  STRATEGY SUMMARY: ENTER ${entering.length} | SKIP ${skipping.length}\n`);
}
