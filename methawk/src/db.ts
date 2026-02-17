/**
 * MetHawk SQLite Database
 * Tracks positions, decisions, rebalances, and daily summaries
 */

import Database from 'better-sqlite3';
import path from 'path';
import { ManagedPosition, RebalanceRecord } from './types/position';

const DB_PATH = path.join(__dirname, '../data/methawk.db');

export class MetHawkDB {
  private db: Database.Database;

  constructor(dbPath: string = DB_PATH) {
    // Ensure data directory exists
    const dir = path.dirname(dbPath);
    const fs = require('fs');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    this.db = new Database(dbPath);
    this.initTables();
  }

  private initTables() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pool_address TEXT NOT NULL,
        pool_name TEXT NOT NULL,
        position_pubkey TEXT,
        token_x_symbol TEXT NOT NULL,
        token_y_symbol TEXT NOT NULL,
        token_x_address TEXT,
        token_y_address TEXT,
        strategy_name TEXT NOT NULL,
        bins INTEGER NOT NULL,
        distribution TEXT NOT NULL,
        rebalance_direction TEXT NOT NULL,
        rebalance_cooldown_min INTEGER NOT NULL,
        entry_time TEXT NOT NULL,
        entry_sol REAL NOT NULL,
        entry_bin_id INTEGER,
        lower_bin_id INTEGER,
        upper_bin_id INTEGER,
        safety_score REAL,
        opportunity_score REAL,
        status TEXT NOT NULL DEFAULT 'active',
        exit_time TEXT,
        exit_sol REAL,
        fees_earned_sol REAL DEFAULT 0,
        fees_earned_usd REAL DEFAULT 0,
        pnl_sol REAL,
        pnl_percent REAL,
        exit_reason TEXT,
        rebalance_count INTEGER DEFAULT 0,
        last_rebalance_time TEXT,
        paper_trade INTEGER NOT NULL DEFAULT 1
      )
    `);

    this.db.exec(`
      CREATE TABLE IF NOT EXISTS rebalances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        direction TEXT NOT NULL,
        old_lower_bin INTEGER,
        old_upper_bin INTEGER,
        new_lower_bin INTEGER,
        new_upper_bin INTEGER,
        old_active_bin INTEGER,
        new_active_bin INTEGER,
        fees_claimed_x REAL DEFAULT 0,
        fees_claimed_y REAL DEFAULT 0,
        tx_signature TEXT,
        FOREIGN KEY (position_id) REFERENCES positions(id)
      )
    `);

    this.db.exec(`
      CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        pool_address TEXT NOT NULL,
        pool_name TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        safety_score REAL,
        opportunity_score REAL,
        strategy_name TEXT,
        paper_trade INTEGER NOT NULL DEFAULT 1
      )
    `);

    this.db.exec(`
      CREATE TABLE IF NOT EXISTS daily_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        total_positions INTEGER NOT NULL DEFAULT 0,
        active_positions INTEGER NOT NULL DEFAULT 0,
        closed_positions INTEGER NOT NULL DEFAULT 0,
        total_pnl_sol REAL NOT NULL DEFAULT 0,
        total_fees_sol REAL NOT NULL DEFAULT 0,
        total_rebalances INTEGER NOT NULL DEFAULT 0
      )
    `);

    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
      CREATE INDEX IF NOT EXISTS idx_rebalances_position ON rebalances(position_id);
      CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
    `);

    // Migrations for new columns
    this.addColumnIfMissing('positions', 'entry_price', 'REAL');
    this.addColumnIfMissing('positions', 'current_price', 'REAL');
    this.addColumnIfMissing('positions', 'current_bin_id', 'INTEGER');
    this.addColumnIfMissing('positions', 'stop_loss_percent', 'REAL');
    this.addColumnIfMissing('positions', 'take_profit_percent', 'REAL');
    this.addColumnIfMissing('positions', 'max_hold_minutes', 'INTEGER');
  }

  private addColumnIfMissing(table: string, column: string, type: string) {
    const cols = this.db.pragma(`table_info(${table})`) as any[];
    if (!cols.find((c: any) => c.name === column)) {
      this.db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`);
    }
  }

  // === Positions ===

  insertPosition(pos: Omit<ManagedPosition, 'id'>): number {
    const stmt = this.db.prepare(`
      INSERT INTO positions (
        pool_address, pool_name, position_pubkey, token_x_symbol, token_y_symbol,
        token_x_address, token_y_address, strategy_name, bins, distribution,
        rebalance_direction, rebalance_cooldown_min, entry_time, entry_sol,
        entry_bin_id, lower_bin_id, upper_bin_id, safety_score, opportunity_score,
        status, rebalance_count, paper_trade,
        stop_loss_percent, take_profit_percent, max_hold_minutes
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const result = stmt.run(
      pos.pool_address, pos.pool_name, pos.position_pubkey,
      pos.token_x_symbol, pos.token_y_symbol, pos.token_x_address, pos.token_y_address,
      pos.strategy_name, pos.bins, pos.distribution,
      pos.rebalance_direction, pos.rebalance_cooldown_min,
      pos.entry_time, pos.entry_sol, pos.entry_bin_id, pos.lower_bin_id, pos.upper_bin_id,
      pos.safety_score, pos.opportunity_score, pos.status, pos.rebalance_count,
      pos.paper_trade ? 1 : 0,
      pos.stop_loss_percent ?? null, pos.take_profit_percent ?? null, pos.max_hold_minutes ?? null
    );
    return result.lastInsertRowid as number;
  }

  getActivePositions(): ManagedPosition[] {
    return this.db.prepare('SELECT * FROM positions WHERE status = ?').all('active') as ManagedPosition[];
  }

  getPosition(id: number): ManagedPosition | undefined {
    return this.db.prepare('SELECT * FROM positions WHERE id = ?').get(id) as ManagedPosition | undefined;
  }

  closePosition(id: number, exitSol: number, feesEarnedSol: number, pnlSol: number, pnlPercent: number, exitReason: string) {
    this.db.prepare(`
      UPDATE positions SET status = 'closed', exit_time = ?, exit_sol = ?,
        fees_earned_sol = ?, pnl_sol = ?, pnl_percent = ?, exit_reason = ?
      WHERE id = ?
    `).run(new Date().toISOString(), exitSol, feesEarnedSol, pnlSol, pnlPercent, exitReason, id);
  }

  updatePositionBins(id: number, lowerBin: number, upperBin: number, rebalanceCount: number) {
    this.db.prepare(`
      UPDATE positions SET lower_bin_id = ?, upper_bin_id = ?, rebalance_count = ?, last_rebalance_time = ?
      WHERE id = ?
    `).run(lowerBin, upperBin, rebalanceCount, new Date().toISOString(), id);
  }

  updatePositionPubkey(id: number, newPubkey: string) {
    this.db.prepare('UPDATE positions SET position_pubkey = ? WHERE id = ?').run(newPubkey, id);
  }

  updatePositionFees(id: number, feesEarnedSol: number) {
    this.db.prepare('UPDATE positions SET fees_earned_sol = ? WHERE id = ?').run(feesEarnedSol, id);
  }

  updatePositionPrice(id: number, currentPrice: number, currentBinId: number) {
    this.db.prepare('UPDATE positions SET current_price = ?, current_bin_id = ? WHERE id = ?')
      .run(currentPrice, currentBinId, id);
  }

  setEntryPrice(id: number, entryPrice: number) {
    this.db.prepare('UPDATE positions SET entry_price = ? WHERE id = ?').run(entryPrice, id);
  }

  // === Rebalances ===

  insertRebalance(record: Omit<RebalanceRecord, 'id'>): number {
    const stmt = this.db.prepare(`
      INSERT INTO rebalances (
        position_id, timestamp, direction, old_lower_bin, old_upper_bin,
        new_lower_bin, new_upper_bin, old_active_bin, new_active_bin,
        fees_claimed_x, fees_claimed_y, tx_signature
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const result = stmt.run(
      record.position_id, record.timestamp, record.direction,
      record.old_lower_bin, record.old_upper_bin,
      record.new_lower_bin, record.new_upper_bin,
      record.old_active_bin, record.new_active_bin,
      record.fees_claimed_x, record.fees_claimed_y, record.tx_signature
    );
    return result.lastInsertRowid as number;
  }

  getRebalancesForPosition(positionId: number): RebalanceRecord[] {
    return this.db.prepare('SELECT * FROM rebalances WHERE position_id = ? ORDER BY timestamp DESC')
      .all(positionId) as RebalanceRecord[];
  }

  // === Decisions ===

  insertDecision(dec: { pool_address: string; pool_name: string; action: string; reason: string; safety_score?: number; opportunity_score?: number; strategy_name?: string; paper_trade: boolean }) {
    this.db.prepare(`
      INSERT INTO decisions (timestamp, pool_address, pool_name, action, reason, safety_score, opportunity_score, strategy_name, paper_trade)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(new Date().toISOString(), dec.pool_address, dec.pool_name, dec.action, dec.reason,
      dec.safety_score, dec.opportunity_score, dec.strategy_name, dec.paper_trade ? 1 : 0);
  }

  // === Stats ===

  getTodayPNL(): number {
    const today = new Date().toISOString().split('T')[0];
    const result = this.db.prepare(`
      SELECT COALESCE(SUM(pnl_sol), 0) as total
      FROM positions WHERE status = 'closed' AND exit_time LIKE ?
    `).get(`${today}%`) as { total: number };
    return result.total;
  }

  getActivePositionCount(): number {
    const result = this.db.prepare('SELECT COUNT(*) as count FROM positions WHERE status = ?')
      .get('active') as { count: number };
    return result.count;
  }

  getTotalDeployedSol(): number {
    const result = this.db.prepare('SELECT COALESCE(SUM(entry_sol), 0) as total FROM positions WHERE status = ?')
      .get('active') as { total: number };
    return result.total;
  }

  close() {
    this.db.close();
  }
}

let dbInstance: MetHawkDB | null = null;

export function getDB(): MetHawkDB {
  if (!dbInstance) {
    dbInstance = new MetHawkDB();
  }
  return dbInstance;
}
