import GoPayMerchant, { loginWithEmailOtp } from './gobiz.js';

const email = process.argv[2] || process.env.GOPAY_EMAIL;
if (!email) {
   console.error('Usage: node auth_email_otp.mjs email@merchant.com');
   process.exit(1);
}

try {
   console.log(`[GoPay Auth] Memulai login email: ${email}`);
   const auth = await loginWithEmailOtp(email);
   const merchant = new GoPayMerchant({ token: auth.access_token });
   await merchant.init();

   console.log('[GoPay Auth] ✅ LOGIN BERHASIL');
   console.log('[GoPay Auth] Merchant ID:', merchant.merchantId);
   console.log('[GoPay Auth] Token dan Merchant ID tersimpan ke .gopay_cache.json');
   console.log('[GoPay Auth] Sekarang backend dapat memakai cache tanpa meminta password.');
} catch (error) {
   console.error('[GoPay Auth] ❌ Gagal:', error?.message || error);
   process.exit(1);
}
