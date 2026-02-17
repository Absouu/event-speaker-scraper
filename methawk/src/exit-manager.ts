/**
 * MetHawk Exit Manager
 * Stop-loss, take-profit, emergency exit, daily loss limit
 */

import { BUDGET, CONFIG } from './config';
import { logger } from './utils/logger';
import { getDB } from './db';
import { closePosition } from './executor';
import { ManagedPosition } from './types/position';
import { notifyEmergencyExit } from './utils/telegram';

/**
 * Check if stop-loss should trigger for a position.
 * Compares current on-chain position value vs entry SOL amount.
 */
export function checkStopLoss(
  position: ManagedPosition,
  currentValueSol: number | null,
): boolean {
  if (currentValueSol === null || currentValueSol < 0) return false;
  const entrySol = position.entry_sol;
  if (entrySol <= 0) return false;

  const lossPct = ((currentValueSol - entrySol) / entrySol) * 100;
  const slThreshold = position.stop_loss_percent ?? BUDGET.STOP_LOSS_PERCENT;

  if (lossPct <= -(slThreshold)) {
    logger.warn('EXIT', `Stop-loss triggered for position ${position.id} (${position.pool_name}): value ${currentValueSol.toFixed(4)} SOL vs entry ${entrySol.toFixed(4)} SOL (${lossPct.toFixed(1)}%, threshold: -${slThreshold}%)`);
    return true;
  }

  return false;
}

/**
 * Check if take-profit should trigger.
 * Uses actual on-chain position value vs entry, NOT accumulated fee counter.
 */
export function checkTakeProfit(
  position: ManagedPosition,
  currentValueSol: number | null,
): boolean {
  if (currentValueSol === null || currentValueSol <= 0) return false;
  const entryAmount = position.entry_sol;
  if (entryAmount <= 0) return false;

  const gainPct = ((currentValueSol - entryAmount) / entryAmount) * 100;
  const tpThreshold = position.take_profit_percent ?? BUDGET.TAKE_PROFIT_PERCENT;

  if (gainPct >= tpThreshold) {
    logger.info('EXIT', `Take-profit triggered for position ${position.id} (${position.pool_name}): value ${currentValueSol.toFixed(4)} SOL vs entry ${entryAmount.toFixed(4)} SOL (+${gainPct.toFixed(1)}%, threshold: +${tpThreshold}%)`);
    return true;
  }

  return false;
}

/**
 * Check if max hold time has been exceeded for a position.
 */
export function checkMaxHoldTime(position: ManagedPosition): boolean {
  if (!position.max_hold_minutes) return false;

  const entryTime = new Date(position.entry_time).getTime();
  const now = Date.now();
  const heldMinutes = (now - entryTime) / (1000 * 60);

  if (heldMinutes >= position.max_hold_minutes) {
    logger.warn('EXIT', `Max hold time exceeded for position ${position.id} (${position.pool_name}): held ${heldMinutes.toFixed(0)}m, limit ${position.max_hold_minutes}m`);
    return true;
  }

  return false;
}

/**
 * Check if daily loss limit has been breached
 */
export function checkDailyLossLimit(): boolean {
  const db = getDB();
  const todayPNL = db.getTodayPNL();
  const totalDeployed = db.getTotalDeployedSol();

  if (totalDeployed <= 0) return false;

  const lossPct = Math.abs(todayPNL) / totalDeployed * 100;

  if (todayPNL < 0 && lossPct >= BUDGET.MAX_DAILY_LOSS_PERCENT) {
    logger.warn('EXIT', `Daily loss limit breached: ${lossPct.toFixed(1)}% loss today`);
    return true;
  }

  return false;
}

/**
 * Emergency exit: close all active positions
 */
export async function emergencyExitAll(reason: string): Promise<void> {
  const db = getDB();
  const activePositions = db.getActivePositions();

  if (activePositions.length === 0) {
    logger.info('EXIT', 'No active positions to exit');
    return;
  }

  logger.warn('EXIT', `EMERGENCY EXIT: Closing ${activePositions.length} positions | Reason: ${reason}`);
  notifyEmergencyExit(activePositions.length, reason);

  for (const pos of activePositions) {
    try {
      await closePosition(pos.id!, `Emergency: ${reason}`);
    } catch (err: any) {
      logger.error('EXIT', `Failed to close position ${pos.id}: ${err.message}`);
    }
  }

  logger.info('EXIT', 'Emergency exit complete');
}

/**
 * Run all exit checks for a position
 * Returns exit reason if should exit, null otherwise
 */
export function shouldExit(
  position: ManagedPosition,
  currentValueSol: number | null,
): string | null {
  // Check take-profit using actual on-chain value
  if (checkTakeProfit(position, currentValueSol)) {
    return 'take_profit';
  }

  // Check stop-loss using actual on-chain position value
  if (checkStopLoss(position, currentValueSol)) {
    return 'stop_loss';
  }

  // Check max hold time
  if (checkMaxHoldTime(position)) {
    return 'max_hold_time';
  }

  return null;
}
