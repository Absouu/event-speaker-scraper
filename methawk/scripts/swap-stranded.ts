/**
 * One-off script to swap stranded tokens back to SOL after failed position entries.
 * Usage: npx ts-node scripts/swap-stranded.ts
 */
import { PublicKey } from '@solana/web3.js';
import { getConnection, getWallet } from '../src/utils/solana';
import { swapTokenToSol } from '../src/utils/jupiter';
const log = (msg: string) => console.log(`[CLEANUP] ${msg}`);

const SOL_MINT = 'So11111111111111111111111111111111111111112';

// Tokens stranded from failed WEN-SOL and URANUS-SOL entries
const STRANDED_MINTS = [
  'WENWENvqqNya429ubCdR81ZmD69brwQaaBYY6p3LCpk',   // WEN
  'BFgdzMkTPdKKJeTipv2njtDEwhKxkgFueJQfJGt1jups', // URANUS
];

async function main() {
  const connection = getConnection();
  const wallet = getWallet();

  log( `Wallet: ${wallet.publicKey.toString()}`);
  const balance = await connection.getBalance(wallet.publicKey);
  log( `SOL balance: ${(balance / 1e9).toFixed(6)} SOL`);

  for (const mint of STRANDED_MINTS) {
    try {
      const tokenAccounts = await connection.getParsedTokenAccountsByOwner(
        wallet.publicKey,
        { mint: new PublicKey(mint) },
      );

      let maxBalance = '0';
      for (const acct of tokenAccounts.value) {
        const amount = acct.account.data.parsed?.info?.tokenAmount?.amount || '0';
        if (BigInt(amount) > BigInt(maxBalance)) maxBalance = amount;
      }

      if (maxBalance === '0' || BigInt(maxBalance) === 0n) {
        log( `No balance for ${mint.slice(0, 8)}... — skipping`);
        continue;
      }

      log( `Found ${maxBalance} raw tokens for ${mint.slice(0, 8)}... — swapping to SOL`);
      const result = await swapTokenToSol(mint, maxBalance, 200);
      log( `Swapped → ${(parseInt(result.outputAmount) / 1e9).toFixed(6)} SOL | tx: ${result.txSignature}`);

      // Wait between swaps
      await new Promise(r => setTimeout(r, 3000));
    } catch (err: any) {
      log( `Failed to swap ${mint.slice(0, 8)}...: ${err.message}`);
    }
  }

  const finalBalance = await connection.getBalance(wallet.publicKey);
  log( `Final SOL balance: ${(finalBalance / 1e9).toFixed(6)} SOL`);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
