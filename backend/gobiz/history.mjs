import GoPayMerchant from "./gobiz.js";

const merchant = new GoPayMerchant();
const result = await merchant.getHistory({ days: 1, size: 100 });

if (!result?.status) {
  throw new Error(result?.message || "Gagal mengambil riwayat GoPay.");
}

const histories = (result.data?.histories || []).map((entry) => {
  const raw = entry.raw || {};
  const txId = raw.transaction_id ?? raw.id ?? raw.order_id ?? null;
  const amount = typeof raw.gross_amount === "number"
    ? raw.gross_amount / 100
    : Number(raw.gross_amount || 0);

  return {
    tx_id: txId,
    amount,
    type: entry.type,
    time: entry.time,
    transaction_time: raw.transaction_time ?? raw.metadata?.transaction?.transaction_time ?? null,
    status: raw.status ?? raw.transaction_status ?? raw.state ?? null,
    payment_type: raw.payment_type ?? raw.payment_method ?? null,
    raw,
  };
});

process.stdout.write(JSON.stringify(histories));
