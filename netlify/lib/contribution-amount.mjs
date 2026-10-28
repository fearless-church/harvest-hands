import verifiedReceipts from './verified-receipts.json' with { type: 'json' };

const included = new Set(['CONFIRMED', 'PAID_OUT', 'PROCESSING', 'PENDING', 'APPROVED']);
const reversed = new Set(['FAILED', 'REFUNDED', 'CHARGEBACK', 'CANCELLED', 'CANCELED']);

export function contributionCents(contribution) {
  const receipt = verifiedReceipts[contribution.id];
  if (receipt) {
    if (reversed.has(contribution.status)) return 0;
    if (contribution.type !== receipt.type) {
      throw new Error('Verified receipt type changed; reconciliation required.');
    }
    if (!included.has(contribution.status) && contribution.status !== 'CONTRIBUTION_RECEIVED') {
      throw new Error('Verified receipt status changed; reconciliation required.');
    }
    return receipt.receivedCents;
  }
  if (!included.has(contribution.status)) return 0;
  if (contribution.amount == null || contribution.amount === '') throw new Error('Missing contribution amount.');
  const amount = Number(contribution.amount);
  if (!Number.isFinite(amount) || amount < 0) throw new Error('Invalid contribution amount.');
  return Math.round((amount + Number.EPSILON) * 100);
}
