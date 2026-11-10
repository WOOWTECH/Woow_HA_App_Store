/** Categorize provider replies without retaining the message or account details. */
export function providerReplyError(text) {
  const reply = String(text || '');
  if (/(?:API Error:|HTTP(?: status(?: code)?)?[:=]?)\s*402\b|\b(?:payment_required|insufficient_credits)\b|upstream provider declined request for billing reason/i.test(reply)) return 'PROVIDER_BILLING_REQUIRED';
  if (/you.ve hit your (?:weekly|daily|monthly|usage|rate) limit|usage[ _]limit[ _]reached|quota (?:exceeded|exhausted)|insufficient_quota/i.test(reply)) return 'PROVIDER_QUOTA_EXHAUSTED';
  if (/(?:API Error:|HTTP(?: status(?: code)?)?[:=]?)\s*429\b|\brate_limit_exceeded\b/i.test(reply)) return 'PROVIDER_RATE_LIMITED';
  if (/(?:API Error:|HTTP(?: status(?: code)?)?[:=]?)\s*401\b|not logged in|please (?:log|sign) in|authentication (?:failed|required)|invalid[ _]api[ _]key|token (?:expired|revoked)/i.test(reply)) return 'PROVIDER_AUTH_REQUIRED';
  return null;
}
