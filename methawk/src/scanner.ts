/**
 * MetHawk Trending Scanner
 * Scans pools via HawkFi API, enriches with DexScreener + Birdeye,
 * classifies market conditions, ranks by fee/TVL ratio.
 */

import { fetchTrendingPools } from './apis/hawkfi';
import { enrichFromBirdeye, isBirdeyeAvailable } from './apis/birdeye';
import { fetchPairByAddress, extractDexScreenerData, searchPairs } from './apis/dexscreener';
import { logger } from './utils/logger';
import { sleep } from './utils/retry';
import { CONFIG, MAJOR_TOKENS, PRE_ENTRY } from './config';
import { EnrichedPool, HawkFiPoolRaw } from './types/pool';

function classifyVolatility(priceChange4h: number, pool: HawkFiPoolRaw): 'low' | 'high' | 'very_high' {
  if (priceChange4h !== 0) {
    const swing = Math.abs(priceChange4h);
    if (swing > 15) return 'very_high';
    if (swing > 5) return 'high';
    return 'low';
  }
  if (pool.volume30m > 0 && pool.volume4h > 0) {
    const rate30m = pool.volume30m * 2;
    const rate4h = pool.volume4h / 4;
    const ratio = rate30m / rate4h;
    if (ratio > 3) return 'very_high';
    if (ratio > 1.5) return 'high';
  }
  return 'low';
}

function classifyVolume(volume1h: number, tvl: number): 'low' | 'high' | 'very_high' {
  if (tvl <= 0) return 'low';
  const ratio = volume1h / tvl;
  if (ratio > 1.0) return 'very_high';
  if (ratio > 0.2) return 'high';
  return 'low';
}

function classifyToken(
  poolName: string,
  poolAgeDays: number,
  holderCount: number,
): 'major' | 'altcoin' | 'memecoin' | 'new_launch' {
  if (poolAgeDays >= 0 && poolAgeDays < 1) return 'new_launch';
  const name = poolName.toUpperCase();
  if (MAJOR_TOKENS.some(m => name.includes(m))) return 'major';
  if (poolAgeDays >= 0 && poolAgeDays < 14 && holderCount < 5000) return 'memecoin';
  return 'altcoin';
}

function classifyTrend(priceChange4h: number, priceChange1h: number): 'uptrend' | 'sideways' | 'downtrend' {
  const change = priceChange4h !== 0 ? priceChange4h : priceChange1h * 2;
  if (change < -10) return 'downtrend';
  if (change > 5) return 'uptrend';
  return 'sideways';
}

function determineVolumeTrend(pool: HawkFiPoolRaw): 'increasing' | 'decreasing' | 'stable' {
  const rate30m = pool.volume30m * 2;
  const rate1h = pool.volume1h;
  const rate4h = pool.volume4h / 4;
  if (rate4h === 0 && rate1h === 0) return 'stable';
  const baseline = rate4h > 0 ? rate4h : rate1h;
  if (baseline === 0) return 'stable';
  const ratio = rate30m / baseline;
  if (ratio > 1.5) return 'increasing';
  if (ratio < 0.5) return 'decreasing';
  return 'stable';
}

/**
 * Pre-entry filters — applied to raw HawkFi data BEFORE enrichment to save API calls.
 * Returns pools that pass all hard gates + the volume decay soft filter.
 */
function applyPreEntryFilters(pools: HawkFiPoolRaw[]): HawkFiPoolRaw[] {
  const before = pools.length;
  const passed: HawkFiPoolRaw[] = [];
  const rejectCounts: Record<string, number> = {};

  for (const pool of pools) {
    // Hard gate: zero recent volume = dead pool
    if (pool.volume30m <= PRE_ENTRY.MIN_VOLUME_30M) {
      rejectCounts['zero_volume_30m'] = (rejectCounts['zero_volume_30m'] || 0) + 1;
      continue;
    }

    // Hard gate: pool not actively generating fees
    const yieldOverTvl = pool.yieldOverTvl30m ?? (pool.tvl > 0 ? pool.yield30m / pool.tvl : 0);
    if (yieldOverTvl < PRE_ENTRY.MIN_YIELD_OVER_TVL_30M) {
      rejectCounts['low_yield_tvl'] = (rejectCounts['low_yield_tvl'] || 0) + 1;
      continue;
    }

    // Hard gate: TVL too low
    if (pool.tvl < PRE_ENTRY.MIN_TVL_USD) {
      rejectCounts['low_tvl'] = (rejectCounts['low_tvl'] || 0) + 1;
      continue;
    }

    // Soft filter: volume decay ratio (volume30m * 48 / volume24h)
    // If 24h volume is 0 but 30m volume > 0, that's fine (new activity)
    if (pool.volume24h > 0) {
      const decayRatio = (pool.volume30m * 48) / pool.volume24h;
      if (decayRatio < PRE_ENTRY.MIN_VOLUME_DECAY_RATIO) {
        rejectCounts['volume_decay'] = (rejectCounts['volume_decay'] || 0) + 1;
        continue;
      }
    }

    passed.push(pool);
  }

  const rejected = before - passed.length;
  if (rejected > 0) {
    const reasons = Object.entries(rejectCounts)
      .map(([k, v]) => `${k}=${v}`)
      .join(', ');
    logger.info('SCANNER', `Pre-entry filter: ${passed.length}/${before} passed (rejected ${rejected}: ${reasons})`);
  } else {
    logger.info('SCANNER', `Pre-entry filter: all ${before} pools passed`);
  }

  return passed;
}

async function enrichPool(pool: HawkFiPoolRaw): Promise<EnrichedPool> {
  const nameParts = pool.name.split(/[-\/]/);
  const enriched: EnrichedPool = {
    address: pool.address,
    name: pool.name,
    protocol: 'meteora',
    binStep: pool.binStep || 0,
    baseFeePercentage: pool.baseFeePercentage || 0,
    tvl: pool.tvl,
    volume24h: pool.volume24h,
    volume7d: pool.volume7d,
    yield24h: pool.yield24h,
    aprDisplay: pool.aprDisplay,
    hawkVolume30m: pool.volume30m,
    hawkVolume1h: pool.volume1h,
    hawkVolume4h: pool.volume4h,
    hawkYield30m: pool.yield30m,
    hawkYield1h: pool.yield1h,
    hawkPoolAgeHours: pool.poolAgeHours,
    hawkOrganicScore: pool.organicScore,
    tokenXAddress: pool.mintA || '',
    tokenXSymbol: nameParts[0]?.trim() || '',
    tokenYAddress: pool.mintB || '',
    tokenYSymbol: nameParts[1]?.trim() || '',
    volume30m: pool.volume30m,
    volume1h: pool.volume1h,
    volume4h: pool.volume4h,
    priceChange1h: 0,
    priceChange4h: 0,
    priceChange24h: 0,
    holderCount: 0,
    poolAgeDays: pool.poolAgeHours > 0 ? pool.poolAgeHours / 24 : -1,
    pairCreatedAt: '',
    volumeH1: pool.volume1h,
    feeTvlRatio: 0,
    volumeTrend: 'stable',
    volatilityLevel: 'low',
    volumeLevel: 'low',
    tokenCategory: 'altcoin',
    priceTrend: 'sideways',
    timestamp: new Date().toISOString(),
  };

  // DexScreener enrichment
  try {
    let dexPair = await fetchPairByAddress(pool.address);
    if (!dexPair && pool.name) {
      const searchResults = await searchPairs(pool.name);
      dexPair = searchResults.find(p => p.dexId === 'meteora' || p.url?.includes('meteora')) || null;
    }
    if (dexPair) {
      const dexData = extractDexScreenerData(dexPair);
      enriched.priceChange1h = dexData.priceChangeH1;
      enriched.priceChange24h = dexData.priceChangeH24;
      enriched.priceChange4h = dexData.priceChangeH6 * 0.67;
      if (enriched.poolAgeDays < 0 && dexData.poolAgeDays >= 0) {
        enriched.poolAgeDays = dexData.poolAgeDays;
      }
      enriched.pairCreatedAt = dexData.pairCreatedAt;
      if (dexPair.baseToken) {
        enriched.tokenXAddress = enriched.tokenXAddress || dexPair.baseToken.address;
        enriched.tokenXSymbol = enriched.tokenXSymbol || dexPair.baseToken.symbol;
      }
      if (dexPair.quoteToken) {
        enriched.tokenYAddress = enriched.tokenYAddress || dexPair.quoteToken.address;
        enriched.tokenYSymbol = enriched.tokenYSymbol || dexPair.quoteToken.symbol;
      }
    }
  } catch (err: any) {
    logger.debug('SCANNER', `DexScreener enrichment failed for ${pool.name}: ${err.message}`);
  }

  // Birdeye enrichment
  if (isBirdeyeAvailable() && enriched.tokenXAddress) {
    try {
      const birdeyeData = await enrichFromBirdeye(enriched.tokenXAddress);
      if (birdeyeData) {
        if (birdeyeData.priceChange1h) enriched.priceChange1h = birdeyeData.priceChange1h;
        if (birdeyeData.priceChange4h) enriched.priceChange4h = birdeyeData.priceChange4h;
        if (birdeyeData.priceChange24h) enriched.priceChange24h = birdeyeData.priceChange24h;
        enriched.holderCount = birdeyeData.holderCount;
      }
    } catch (err: any) {
      logger.debug('SCANNER', `Birdeye enrichment failed for ${pool.name}: ${err.message}`);
    }
  }

  // Compute derived metrics
  if (pool.yieldOverTvl30m && pool.yieldOverTvl30m > 0) {
    enriched.feeTvlRatio = pool.yieldOverTvl30m;
  } else if (enriched.tvl > 0) {
    enriched.feeTvlRatio = enriched.yield24h / enriched.tvl;
  }

  enriched.volatilityLevel = classifyVolatility(enriched.priceChange4h, pool);
  enriched.volumeLevel = classifyVolume(enriched.volume1h, enriched.tvl);
  enriched.tokenCategory = classifyToken(enriched.name, enriched.poolAgeDays, enriched.holderCount);
  enriched.priceTrend = classifyTrend(enriched.priceChange4h, enriched.priceChange1h);
  enriched.volumeTrend = determineVolumeTrend(pool);

  return enriched;
}

function createBasicEnrichedPool(pool: HawkFiPoolRaw): EnrichedPool {
  const nameParts = pool.name.split(/[-\/]/);
  return {
    address: pool.address, name: pool.name, protocol: 'meteora',
    binStep: pool.binStep || 0, baseFeePercentage: pool.baseFeePercentage || 0,
    tvl: pool.tvl, volume24h: pool.volume24h, volume7d: pool.volume7d,
    yield24h: pool.yield24h, aprDisplay: pool.aprDisplay,
    hawkVolume30m: pool.volume30m, hawkVolume1h: pool.volume1h, hawkVolume4h: pool.volume4h,
    hawkYield30m: pool.yield30m, hawkYield1h: pool.yield1h,
    hawkPoolAgeHours: pool.poolAgeHours, hawkOrganicScore: pool.organicScore,
    tokenXAddress: pool.mintA || '', tokenXSymbol: nameParts[0]?.trim() || '',
    tokenYAddress: pool.mintB || '', tokenYSymbol: nameParts[1]?.trim() || '',
    volume30m: pool.volume30m, volume1h: pool.volume1h, volume4h: pool.volume4h,
    priceChange1h: 0, priceChange4h: 0, priceChange24h: 0, holderCount: 0,
    poolAgeDays: pool.poolAgeHours > 0 ? pool.poolAgeHours / 24 : -1,
    pairCreatedAt: '', volumeH1: pool.volume1h,
    feeTvlRatio: pool.tvl > 0 ? pool.yield24h / pool.tvl : 0,
    volumeTrend: determineVolumeTrend(pool),
    volatilityLevel: 'low',
    volumeLevel: classifyVolume(pool.volume1h, pool.tvl),
    tokenCategory: classifyToken(pool.name, pool.poolAgeHours / 24, 0),
    priceTrend: 'sideways',
    timestamp: new Date().toISOString(),
  };
}

function formatNumber(n: number): string {
  if (!n || isNaN(n)) return '0';
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  if (n >= 1) return n.toFixed(2);
  return n.toFixed(4);
}

function displayScanResults(pools: EnrichedPool[]): void {
  logger.separator('SCANNER', 'ENRICHED TRENDING SCAN RESULTS');
  const headers = ['#', 'Pool', 'Yield24h', 'APR', 'TVL', 'HkVol1h', 'Price1h', 'Price4h',
    'Age(d)', 'Volatility', 'Volume', 'Category', 'Trend', 'Fee/TVL', 'VolTrend'];
  const rows = pools.map((p, i) => [
    String(i + 1),
    (p.name || '?').substring(0, 16).padEnd(16),
    `$${formatNumber(p.yield24h)}`,
    `${((p.aprDisplay || 0) * 100).toFixed(0)}%`,
    `$${formatNumber(p.tvl)}`,
    `$${formatNumber(p.hawkVolume1h)}`,
    p.priceChange1h ? `${p.priceChange1h > 0 ? '+' : ''}${p.priceChange1h.toFixed(1)}%` : '-',
    p.priceChange4h ? `${p.priceChange4h > 0 ? '+' : ''}${p.priceChange4h.toFixed(1)}%` : '-',
    p.poolAgeDays >= 0 ? p.poolAgeDays.toFixed(0) : '?',
    p.volatilityLevel.substring(0, 6),
    p.volumeLevel.substring(0, 6),
    p.tokenCategory.substring(0, 8),
    p.priceTrend.substring(0, 8),
    p.feeTvlRatio > 0 ? p.feeTvlRatio.toFixed(4) : '-',
    p.volumeTrend.substring(0, 5),
  ]);
  logger.table('SCANNER', headers, rows);
}

export async function runTrendingScan(
  poolLimit: number = 50,
  enrichLimit: number = 30,
): Promise<EnrichedPool[]> {
  logger.separator('SCANNER', `TRENDING SCAN - ${new Date().toISOString()}`);

  logger.info('SCANNER', `Fetching top ${poolLimit} pools from HawkFi...`);
  let rawPools: HawkFiPoolRaw[];
  try {
    rawPools = await fetchTrendingPools(poolLimit, 'yield1h', 'meteora');
  } catch (err: any) {
    logger.warn('SCANNER', `Meteora filter failed, trying all: ${err.message}`);
    rawPools = await fetchTrendingPools(poolLimit, 'yield1h', '');
  }

  if (rawPools.length === 0) {
    logger.warn('SCANNER', 'No pools returned from HawkFi');
    return [];
  }
  logger.info('SCANNER', `Got ${rawPools.length} raw pools`);

  // Apply pre-entry filters before enrichment (saves API calls on dead pools)
  const filtered = applyPreEntryFilters(rawPools);
  if (filtered.length === 0) {
    logger.warn('SCANNER', 'All pools rejected by pre-entry filters');
    return [];
  }

  const toEnrich = filtered.slice(0, enrichLimit);
  logger.info('SCANNER', `Enriching top ${toEnrich.length} pools...`);

  const enrichedPools: EnrichedPool[] = [];
  for (let i = 0; i < toEnrich.length; i++) {
    const pool = toEnrich[i];
    try {
      const enriched = await enrichPool(pool);
      enrichedPools.push(enriched);
      if (i < toEnrich.length - 1) await sleep(300);
    } catch (err: any) {
      logger.warn('SCANNER', `Failed to enrich ${pool.name}: ${err.message}`);
      enrichedPools.push(createBasicEnrichedPool(pool));
    }
  }

  enrichedPools.sort((a, b) => b.feeTvlRatio - a.feeTvlRatio);
  displayScanResults(enrichedPools);
  return enrichedPools;
}

export async function startTrendingLoop(): Promise<void> {
  logger.info('SCANNER', `Starting scanner loop (interval: ${CONFIG.SCAN_INTERVAL_MS / 1000}s)`);
  await runTrendingScan();
  setInterval(async () => {
    try {
      await runTrendingScan();
    } catch (err: any) {
      logger.error('SCANNER', `Scan loop error: ${err.message}`);
    }
  }, CONFIG.SCAN_INTERVAL_MS);
}
