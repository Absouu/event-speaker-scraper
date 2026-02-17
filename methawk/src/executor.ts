/**
 * MetHawk DLMM Position Executor
 * Creates, manages, and closes positions via @meteora-ag/dlmm SDK
 */

import { PublicKey, Keypair, Transaction } from '@solana/web3.js';
import DLMM from '@meteora-ag/dlmm';
import BN from 'bn.js';
import { getConnection, getWallet, signAndSendTransaction } from './utils/solana';
import { CONFIG, BUDGET } from './config';
import { logger } from './utils/logger';
import { toMeteorStrategyType, StrategyDecision } from './strategy';
import { getDB } from './db';
import { ManagedPosition } from './types/position';
import { notifyPositionClosed } from './utils/telegram';
import { swapSolToToken, swapTokenToSol, getMarketValueInSol } from './utils/jupiter';

const LAMPORTS_PER_SOL = 1_000_000_000;
const SOL_MINT = 'So11111111111111111111111111111111111111112';

export interface CreatePositionParams {
  poolAddress: string;
  poolName: string;
  solAmount: number;
  strategy: StrategyDecision;
  safetyScore: number;
  opportunityScore: number;
  tokenXSymbol: string;
  tokenYSymbol: string;
  tokenXAddress: string;
  tokenYAddress: string;
}

export interface PositionInfo {
  positionPubkey: PublicKey;
  lowerBinId: number;
  upperBinId: number;
  activeBinId: number;
  activeBinPrice: number;
  totalXAmount: string;
  totalYAmount: string;
  feeX: string;
  feeY: string;
  inRange: boolean;
}

/**
 * Get a DLMM pool instance
 */
export async function getDLMMPool(poolAddress: string): Promise<DLMM> {
  const connection = getConnection();
  const pubkey = new PublicKey(poolAddress);
  return DLMM.create(connection, pubkey);
}

/**
 * Get current active bin for a pool
 */
export async function getActiveBin(dlmmPool: DLMM): Promise<{ binId: number; price: number }> {
  const activeBin = await dlmmPool.getActiveBin();
  return {
    binId: activeBin.binId,
    price: parseFloat(activeBin.price),
  };
}

/**
 * Create a new LP position on a Meteora DLMM pool
 */
export async function createPosition(params: CreatePositionParams): Promise<number> {
  const db = getDB();
  const isPaper = CONFIG.PAPER_TRADE_MODE;
  const { poolAddress, poolName, solAmount, strategy, safetyScore, opportunityScore } = params;

  logger.info('EXECUTOR', `Creating position: ${poolName} | ${solAmount} SOL | ${strategy.preset.name}`);

  if (isPaper) {
    // Paper trade: query real active bin for price tracking
    let entryBinId = 0;
    let entryPrice = 0;
    let lowerBin = strategy.binRange.lower;
    let upperBin = strategy.binRange.upper;
    try {
      const dlmmPool = await getDLMMPool(poolAddress);
      const activeBin = await getActiveBin(dlmmPool);
      entryBinId = activeBin.binId;
      entryPrice = activeBin.price;
      const halfBins = Math.floor(strategy.preset.bins / 2);
      lowerBin = activeBin.binId - halfBins;
      upperBin = activeBin.binId + halfBins;
      logger.info('EXECUTOR', `[PAPER] Real active bin: ${activeBin.binId} (price: ${activeBin.price})`);
    } catch (err: any) {
      logger.warn('EXECUTOR', `[PAPER] Could not fetch active bin: ${err.message}`);
    }

    const posId = db.insertPosition({
      pool_address: poolAddress,
      pool_name: poolName,
      position_pubkey: `paper_${Date.now()}`,
      token_x_symbol: params.tokenXSymbol,
      token_y_symbol: params.tokenYSymbol,
      token_x_address: params.tokenXAddress,
      token_y_address: params.tokenYAddress,
      strategy_name: strategy.preset.name,
      bins: strategy.preset.bins,
      distribution: strategy.preset.distribution,
      rebalance_direction: strategy.preset.rebalanceDirection,
      rebalance_cooldown_min: strategy.preset.rebalanceCooldownMin,
      entry_time: new Date().toISOString(),
      entry_sol: solAmount,
      entry_bin_id: entryBinId,
      lower_bin_id: lowerBin,
      upper_bin_id: upperBin,
      safety_score: safetyScore,
      opportunity_score: opportunityScore,
      status: 'active',
      rebalance_count: 0,
      paper_trade: true,
      stop_loss_percent: strategy.preset.stopLossPercent,
      take_profit_percent: strategy.preset.takeProfitPercent,
      max_hold_minutes: strategy.preset.maxHoldMinutes,
    });

    if (entryPrice > 0) {
      db.setEntryPrice(posId, entryPrice);
    }

    logger.info('EXECUTOR', `[PAPER] Position created: ID=${posId} | ${poolName} | ${solAmount} SOL`);
    return posId;
  }

  // Live execution
  try {
    const dlmmPool = await getDLMMPool(poolAddress);
    const wallet = getWallet();
    const activeBin = await getActiveBin(dlmmPool);

    logger.info('EXECUTOR', `Active bin: ${activeBin.binId} (price: ${activeBin.price})`);

    // Calculate bin range
    const halfBins = Math.floor(strategy.preset.bins / 2);
    const minBinId = activeBin.binId - halfBins;
    const maxBinId = activeBin.binId + halfBins;

    // Determine which token is SOL
    const solIsTokenX = params.tokenXAddress === SOL_MINT;
    const solIsTokenY = params.tokenYAddress === SOL_MINT;

    if (!solIsTokenX && !solIsTokenY) {
      throw new Error(`Cannot enter pool without SOL token: ${params.tokenXSymbol}/${params.tokenYSymbol}`);
    }

    const otherTokenMint = solIsTokenX ? params.tokenYAddress : params.tokenXAddress;
    const otherTokenSymbol = solIsTokenX ? params.tokenYSymbol : params.tokenXSymbol;

    // Pre-entry check: compare pool price vs Jupiter market price
    // If divergence > 15%, the pool is stale and we'd lose money on entry
    const testAmount = Math.floor(0.1 * LAMPORTS_PER_SOL); // quote 0.1 SOL worth
    const poolPricePerToken = solIsTokenX ? (1 / activeBin.price) : activeBin.price;
    // Use Jupiter to check: swap testAmount SOL → other token, then see implied price
    try {
      const { data: testQuote } = await (await import('axios')).default.get(`https://public.jupiterapi.com/quote`, {
        params: { inputMint: SOL_MINT, outputMint: otherTokenMint, amount: testAmount.toString(), slippageBps: 100 },
      });
      const outTokens = parseFloat(testQuote.outAmount);
      const decOther = (dlmmPool as any).tokenX?.decimal ?? (dlmmPool as any).tokenY?.decimal ?? 9;
      const jupiterPricePerToken = (testAmount / 1e9) / (outTokens / Math.pow(10, decOther));
      const divergencePct = Math.abs(poolPricePerToken - jupiterPricePerToken) / jupiterPricePerToken * 100;

      logger.info('EXECUTOR', `Price check: pool=${poolPricePerToken.toFixed(8)} vs jupiter=${jupiterPricePerToken.toFixed(8)} (${divergencePct.toFixed(1)}% divergence)`);

      if (divergencePct > 15) {
        throw new Error(`Pool price diverges ${divergencePct.toFixed(1)}% from market — skipping to avoid instant loss`);
      }
    } catch (err: any) {
      if (err.message.includes('diverges')) throw err;
      logger.warn('EXECUTOR', `Price divergence check failed: ${err.message} — proceeding with caution`);
    }

    // Swap half SOL → other token via Jupiter for two-sided entry
    const halfLamports = Math.floor(solAmount * LAMPORTS_PER_SOL / 2);
    logger.info('EXECUTOR', `Swapping ${(halfLamports / LAMPORTS_PER_SOL).toFixed(4)} SOL → ${otherTokenSymbol} via Jupiter`);
    const swapResult = await swapSolToToken(otherTokenMint, halfLamports, BUDGET.DEFAULT_SLIPPAGE_BPS);

    // Build both-sided amounts
    const solSide = new BN(halfLamports);
    const otherSide = new BN(swapResult.outputAmount);

    let totalXAmount: BN;
    let totalYAmount: BN;

    if (solIsTokenX) {
      totalXAmount = solSide;       // SOL
      totalYAmount = otherSide;     // swapped token
    } else {
      totalXAmount = otherSide;     // swapped token
      totalYAmount = solSide;       // SOL
    }

    logger.info('EXECUTOR', `Two-sided entry: X=${totalXAmount.toString()} Y=${totalYAmount.toString()}`);

    // Inner try/catch: if position creation fails after swap, recover tokens
    try {
      // Generate position keypair
      const positionKeypair = Keypair.generate();

      const strategyType = toMeteorStrategyType(strategy.preset.distribution);

      // Create position and add liquidity
      const createTx = await dlmmPool.initializePositionAndAddLiquidityByStrategy({
        positionPubKey: positionKeypair.publicKey,
        totalXAmount,
        totalYAmount,
        strategy: {
          maxBinId,
          minBinId,
          strategyType,
        },
        user: wallet.publicKey,
        slippage: BUDGET.DEFAULT_SLIPPAGE_BPS,
      });

      // Sign with both wallet and position keypair
      const connection = getConnection();
      const { blockhash } = await connection.getLatestBlockhash();

      for (const tx of Array.isArray(createTx) ? createTx : [createTx]) {
        if (tx instanceof Transaction) {
          tx.feePayer = wallet.publicKey;
          tx.recentBlockhash = blockhash;
          tx.sign(wallet, positionKeypair);
          await connection.sendRawTransaction(tx.serialize(), { skipPreflight: false });
        }
      }

      logger.info('EXECUTOR', `Position created on-chain: ${positionKeypair.publicKey.toString()}`);

      // Record in DB
      const posId = db.insertPosition({
        pool_address: poolAddress,
        pool_name: poolName,
        position_pubkey: positionKeypair.publicKey.toString(),
        token_x_symbol: params.tokenXSymbol,
        token_y_symbol: params.tokenYSymbol,
        token_x_address: params.tokenXAddress,
        token_y_address: params.tokenYAddress,
        strategy_name: strategy.preset.name,
        bins: strategy.preset.bins,
        distribution: strategy.preset.distribution,
        rebalance_direction: strategy.preset.rebalanceDirection,
        rebalance_cooldown_min: strategy.preset.rebalanceCooldownMin,
        entry_time: new Date().toISOString(),
        entry_sol: solAmount,
        entry_bin_id: activeBin.binId,
        lower_bin_id: minBinId,
        upper_bin_id: maxBinId,
        safety_score: safetyScore,
        opportunity_score: opportunityScore,
        status: 'active',
        rebalance_count: 0,
        paper_trade: false,
        stop_loss_percent: strategy.preset.stopLossPercent,
        take_profit_percent: strategy.preset.takeProfitPercent,
        max_hold_minutes: strategy.preset.maxHoldMinutes,
      });

      db.setEntryPrice(posId, activeBin.price);
      logger.info('EXECUTOR', `Position recorded: ID=${posId} | bins [${minBinId}, ${maxBinId}] | price ${activeBin.price}`);
      return posId;
    } catch (posErr: any) {
      // Position creation failed after Jupiter swap — swap tokens back to SOL
      logger.error('EXECUTOR', `Position creation failed after swap: ${posErr.message}`);
      logger.info('EXECUTOR', `Recovering stranded ${otherTokenSymbol} tokens back to SOL...`);
      try {
        const connection = getConnection();
        const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
          wallet.publicKey,
          { mint: new PublicKey(otherTokenMint) },
        );
        let tokenBalance = '0';
        for (const acct of tokenAccounts.value) {
          const amount = acct.account.data.parsed?.info?.tokenAmount?.amount || '0';
          if (BigInt(amount) > BigInt(tokenBalance)) tokenBalance = amount;
        }
        if (tokenBalance !== '0' && BigInt(tokenBalance) > 0n) {
          const recoveryResult = await swapTokenToSol(otherTokenMint, tokenBalance, 200);
          logger.info('EXECUTOR', `Recovered ${(parseInt(recoveryResult.outputAmount) / 1e9).toFixed(6)} SOL from stranded ${otherTokenSymbol}`);
        }
      } catch (recoveryErr: any) {
        logger.error('EXECUTOR', `Failed to recover stranded ${otherTokenSymbol}: ${recoveryErr.message}. Manual swap needed for mint ${otherTokenMint}`);
      }
      throw posErr;
    }
  } catch (err: any) {
    logger.error('EXECUTOR', `Failed to create position: ${err.message}`);
    db.insertDecision({
      pool_address: poolAddress,
      pool_name: poolName,
      action: 'error',
      reason: `Create failed: ${err.message}`,
      paper_trade: isPaper,
    });
    throw err;
  }
}

/**
 * Close a position - withdraw all liquidity and claim fees
 */
export async function closePosition(positionId: number, reason: string): Promise<void> {
  const db = getDB();
  const pos = db.getPosition(positionId);
  if (!pos) throw new Error(`Position ${positionId} not found`);
  if (pos.status !== 'active') throw new Error(`Position ${positionId} is ${pos.status}`);

  logger.info('EXECUTOR', `Closing position ${positionId}: ${pos.pool_name} | Reason: ${reason}`);

  if (pos.paper_trade) {
    // Paper trade: just update DB
    const pnl = 0; // Paper positions don't track real P&L
    const feesSol = pos.fees_earned_sol || 0;
    db.closePosition(positionId, pos.entry_sol, feesSol, pnl, 0, reason);
    logger.info('EXECUTOR', `[PAPER] Position ${positionId} closed`);
    notifyPositionClosed(positionId, pos.pool_name, reason, pnl, feesSol);
    return;
  }

  try {
    const dlmmPool = await getDLMMPool(pos.pool_address);
    const wallet = getWallet();
    const positionPubkey = new PublicKey(pos.position_pubkey);

    // Get position data
    const { userPositions } = await dlmmPool.getPositionsByUserAndLbPair(wallet.publicKey);
    const position = userPositions.find(p => p.publicKey.equals(positionPubkey));

    if (!position) {
      logger.warn('EXECUTOR', `Position not found on-chain, marking as closed`);
      db.closePosition(positionId, 0, 0, -(pos.entry_sol), -100, `${reason} (not found on-chain)`);
      return;
    }

    // Remove all liquidity and close
    const binData = position.positionData.positionBinData as any[];
    const binIds = binData.map((bin: any) => bin.binId);
    const fromBinId = Math.min(...binIds);
    const toBinId = Math.max(...binIds);

    const removeTxs = await dlmmPool.removeLiquidity({
      user: wallet.publicKey,
      position: position.publicKey,
      fromBinId,
      toBinId,
      bps: new BN(10000), // 100%
      shouldClaimAndClose: true,
    });

    const connection = getConnection();
    for (const tx of Array.isArray(removeTxs) ? removeTxs : [removeTxs]) {
      if (tx instanceof Transaction) {
        await signAndSendTransaction(tx);
      }
    }

    logger.info('EXECUTOR', `Liquidity removed from ${pos.pool_name}, swapping tokens back to SOL...`);

    // Swap the non-SOL token back to SOL
    const solIsX = pos.token_x_address === SOL_MINT;
    const otherMint = solIsX ? pos.token_y_address : pos.token_x_address;
    const otherSymbol = solIsX ? pos.token_y_symbol : pos.token_x_symbol;

    let swapBackSol = 0;
    try {
      // Check wallet balance of the non-SOL token
      const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
        wallet.publicKey,
        { mint: new PublicKey(otherMint) },
      );

      let tokenBalance = '0';
      for (const acct of tokenAccounts.value) {
        const amount = acct.account.data.parsed?.info?.tokenAmount?.amount || '0';
        if (BigInt(amount) > BigInt(tokenBalance)) tokenBalance = amount;
      }

      if (tokenBalance !== '0' && BigInt(tokenBalance) > 0n) {
        logger.info('EXECUTOR', `Swapping ${tokenBalance} raw ${otherSymbol} → SOL`);
        const swapResult = await swapTokenToSol(otherMint, tokenBalance, 150);
        swapBackSol = parseInt(swapResult.outputAmount) / 1e9;
        logger.info('EXECUTOR', `Swapped ${otherSymbol} → ${swapBackSol.toFixed(6)} SOL`);
      } else {
        logger.info('EXECUTOR', `No ${otherSymbol} balance to swap back`);
      }
    } catch (err: any) {
      logger.error('EXECUTOR', `Failed to swap ${otherSymbol} back to SOL: ${err.message}`);
      logger.warn('EXECUTOR', `Manual swap needed for remaining ${otherSymbol} tokens`);
    }

    // Calculate P&L using actual SOL recovered
    const feesSol = pos.fees_earned_sol || 0;
    // Get current SOL balance after close to estimate total recovered
    const postBalance = await connection.getBalance(wallet.publicKey);
    const postBalanceSol = postBalance / 1e9;
    const exitSol = pos.entry_sol + swapBackSol; // approximate
    const pnlSol = (exitSol - pos.entry_sol) + feesSol;
    const pnlPct = pos.entry_sol > 0 ? (pnlSol / pos.entry_sol) * 100 : 0;

    db.closePosition(positionId, exitSol, feesSol, pnlSol, pnlPct, reason);
    logger.info('EXECUTOR', `Position ${positionId} closed on-chain | P&L: ${pnlSol.toFixed(4)} SOL | Wallet: ${postBalanceSol.toFixed(4)} SOL`);
    notifyPositionClosed(positionId, pos.pool_name, reason, pnlSol, feesSol);
  } catch (err: any) {
    logger.error('EXECUTOR', `Failed to close position ${positionId}: ${err.message}`);
    throw err;
  }
}

/**
 * Get status of a position relative to current active bin
 */
export async function getPositionStatus(pos: ManagedPosition): Promise<PositionInfo | null> {
  if (pos.paper_trade) {
    // Paper positions: query real active bin for accurate tracking
    try {
      const dlmmPool = await getDLMMPool(pos.pool_address);
      const activeBin = await getActiveBin(dlmmPool);
      const inRange = activeBin.binId >= pos.lower_bin_id && activeBin.binId <= pos.upper_bin_id;
      return {
        positionPubkey: new PublicKey('11111111111111111111111111111111'),
        lowerBinId: pos.lower_bin_id,
        upperBinId: pos.upper_bin_id,
        activeBinId: activeBin.binId,
        activeBinPrice: activeBin.price,
        totalXAmount: '0',
        totalYAmount: '0',
        feeX: '0',
        feeY: '0',
        inRange,
      };
    } catch {
      // Fallback if pool query fails
      return {
        positionPubkey: new PublicKey('11111111111111111111111111111111'),
        lowerBinId: pos.lower_bin_id,
        upperBinId: pos.upper_bin_id,
        activeBinId: pos.entry_bin_id,
        activeBinPrice: pos.current_price || 0,
        totalXAmount: '0',
        totalYAmount: '0',
        feeX: '0',
        feeY: '0',
        inRange: true,
      };
    }
  }

  try {
    const dlmmPool = await getDLMMPool(pos.pool_address);
    const activeBin = await getActiveBin(dlmmPool);

    const inRange = activeBin.binId >= pos.lower_bin_id && activeBin.binId <= pos.upper_bin_id;

    return {
      positionPubkey: new PublicKey(pos.position_pubkey),
      lowerBinId: pos.lower_bin_id,
      upperBinId: pos.upper_bin_id,
      activeBinId: activeBin.binId,
      activeBinPrice: activeBin.price,
      totalXAmount: '0', // Would need to query position data
      totalYAmount: '0',
      feeX: '0',
      feeY: '0',
      inRange,
    };
  } catch (err: any) {
    logger.warn('EXECUTOR', `Failed to get position status: ${err.message}`);
    return null;
  }
}

/**
 * Query on-chain position value in SOL using Jupiter market prices.
 * Uses actual market price (not pool's internal price which can be stale).
 */
export async function getPositionValueInSol(pos: ManagedPosition): Promise<number | null> {
  if (pos.paper_trade) return null;

  try {
    const dlmmPool = await getDLMMPool(pos.pool_address);
    const wallet = getWallet();
    const posKey = new PublicKey(pos.position_pubkey);

    const { userPositions } = await dlmmPool.getPositionsByUserAndLbPair(wallet.publicKey);
    const onChainPos = userPositions.find((p: any) => p.publicKey.equals(posKey));

    if (!onChainPos) {
      logger.warn('EXECUTOR', `Position ${pos.id} not found on-chain`);
      return null;
    }

    const pData = onChainPos.positionData;

    // Use SDK-provided totals (more reliable than summing bins)
    const totalXRaw = parseFloat(pData.totalXAmount?.toString() || '0');
    const totalYRaw = parseFloat(pData.totalYAmount?.toString() || '0');

    // Include unclaimed fees
    const feeXRaw = parseFloat(pData.feeX?.toString() || '0');
    const feeYRaw = parseFloat(pData.feeY?.toString() || '0');

    const solIsX = pos.token_x_address === SOL_MINT;
    const solRaw = (solIsX ? totalXRaw : totalYRaw) + (solIsX ? feeXRaw : feeYRaw);
    const otherRaw = (solIsX ? totalYRaw : totalXRaw) + (solIsX ? feeYRaw : feeXRaw);
    const otherMint = solIsX ? pos.token_y_address : pos.token_x_address;

    // SOL portion: convert from lamports
    let solValue = solRaw / 1e9;

    // Non-SOL portion: get Jupiter market price
    if (otherRaw > 0) {
      const otherValueSol = await getMarketValueInSol(otherMint, Math.floor(otherRaw).toString());
      if (otherValueSol > 0) {
        solValue += otherValueSol;
      }
    }

    logger.debug('EXECUTOR', `Position ${pos.id} market value: ${solValue.toFixed(6)} SOL (SOL: ${(solRaw / 1e9).toFixed(6)}, other: ${Math.floor(otherRaw)} raw → Jupiter, fees: X=${feeXRaw} Y=${feeYRaw})`);
    return solValue;
  } catch (err: any) {
    logger.warn('EXECUTOR', `Could not get position value for ${pos.id}: ${err.message}`);
    return null;
  }
}
