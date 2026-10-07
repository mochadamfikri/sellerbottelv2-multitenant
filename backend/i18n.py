STRINGS = {
    "id": {
        "choose_currency": "🏪 <b>Selamat datang di Toko Produk Digital!</b>\n\nSilakan pilih mata uang yang ingin Anda gunakan:\n\n💵 <b>USD</b> — deposit via crypto (USDT/USDC)\n🇮🇩 <b>IDR</b> — deposit via transfer bank\n\nPilihan ini bisa diubah kapan saja lewat menu Pengaturan.",
        "main_title": "🏪 <b>Toko Produk Digital</b>\n\nHalo, {name}! 👋\nSaldo Anda: <b>{balance}</b>\n\nSilakan pilih menu:",
        "btn_products": "📚 Katalog Produk", "btn_cart": "🛒 Keranjang", "btn_deposit": "💰 Deposit",
        "btn_balance": "💳 Saldo Saya", "btn_history": "📜 Riwayat", "btn_settings": "⚙️ Pengaturan",
        "btn_help": "❓ Bantuan", "btn_stock": "📦 Stok", "btn_main": "🏠 Menu Utama", "btn_back": "◀️ Kembali",
        "btn_cancel": "❌ Batal", "btn_buy": "🛒 Beli Sekarang ({price})", "btn_add_cart": "➕ Tambah ke Keranjang",
        "btn_view_cart": "🛒 Lihat Keranjang", "btn_continue": "🛍 Lanjut Belanja",
        "btn_checkout": "✅ Checkout ({total})", "btn_clear": "🧹 Kosongkan", "btn_deposit_now": "💰 Deposit Sekarang",
        "btn_change_currency": "🔄 Ganti ke {cur}", "btn_language": "🌐 Bahasa / Language",
        "btn_convert_yes": "✅ Ya, konversi saldo", "btn_convert_no": "❌ Tidak, saldo tetap terpisah",
        "btn_menu_short": "🏠 Menu", "btn_other_network": "◀️ Pilih Jaringan Lain", "btn_remove": "🗑 Hapus",
        "products_title": "🛍 <b>Daftar Produk</b>\n\nKlik produk untuk melihat detail:",
        "no_products": "🛍 <b>Produk</b>\n\nBelum ada produk tersedia saat ini.",
        "product_not_found": "Produk tidak ditemukan.",
        "prod_detail": "📦 <b>{name}</b>\n\n{desc}\n\nJenis: {type}\nHarga: <b>{price}</b>\nStok tersedia: <b>{stock}</b>",
        "type_file": "📁 File", "type_link": "🔗 Link", "type_license": "🔑 Kode Lisensi", "type_inventory": "👤 Akun / Inventory",
        "stock_word": "stok", "out_of_stock": "❌ <b>Stok habis</b> — produk ini sedang tidak tersedia.",
        "stock_title": "📦 <b>Stok Produk Tersedia</b>\n",
        "stock_empty": "Belum ada produk.",
        "stock_legend": (
            "\n🎨 Warna tombol menunjukkan <b>ketersediaan stok</b> (bukan kondisi produk):\n"
            "🔴 Merah: stok 1–4 (hampir habis)\n"
            "🟢 Hijau: stok 5–9\n"
            "🔵 Biru: stok 10 ke atas"
        ),
        "added_cart": "✅ Produk ditambahkan ke keranjang!",
        "qty_max": "⚠️ Jumlah melebihi stok tersedia ({stock}).",
        "cart_empty": "🛒 <b>Keranjang</b>\n\nKeranjang Anda kosong.",
        "cart_title": "🛒 <b>Keranjang Anda</b>\n\nGunakan tombol ➖ ➕ untuk mengubah jumlah:",
        "cart_total": "Total: <b>{total}</b>",
        "cart_cleared": "🧹 Keranjang dikosongkan.",
        "no_valid_products": "Tidak ada produk valid untuk dibeli.",
        "insufficient": "⚠️ <b>Saldo Tidak Cukup</b>\n\nTotal belanja: <b>{total}</b>\nSaldo Anda: {balance}\nKekurangan: <b>{short}</b>\n\nSilakan deposit terlebih dahulu.",
        "stock_insufficient": "⚠️ Stok <b>{name}</b> tidak cukup (tersisa {stock}). Sesuaikan jumlah di keranjang.",
        "pay_success": "✅ <b>Pembayaran Berhasil!</b>\n\nTotal: <b>{total}</b>\nProduk sedang dikirim...",
        "delivered_all": "🎉 Semua produk telah dikirim!\nSisa saldo: <b>{balance}</b>",
        "deliver_fail": "⚠️ Gagal mengirim file <b>{name}</b>. Hubungi admin.",
        
        "order_refunded": "💸 <b>Refund Order</b>\n\nInvoice <code>{invoice}</code> telah direfund sebesar <b>{amount}</b> dan saldo Anda dikembalikan.",
        "checkout_in_progress": "⏳ Checkout Anda sedang diproses. Tunggu proses sebelumnya selesai.",
        "checkout_failed": "⚠️ Checkout gagal diproses. Saldo dan stok tidak berubah. Silakan coba lagi.",
        "delivery_attention": "⚠️ Invoice <code>{invoice}</code> tercatat, tetapi ada produk yang gagal dikirim. Hubungi admin.",
        "deliver_link": "📦 <b>{name}</b>\n\n🔗 Link produk Anda:\n{content}",
        "deliver_license": "📦 <b>{name}</b>\n\n🔑 Kode lisensi Anda:\n<code>{content}</code>",
        "dep_usd_title": "💰 <b>Deposit USD</b>\n\nMinimum deposit: <b>${min:,.2f}</b>\n\nPilih koin:",
        "choose_network": "💰 <b>Deposit {coin}</b>\n\nPilih jaringan:",
        "dep_no_bank": "💰 <b>Deposit IDR</b>\n\n⚠️ Rekening bank belum dikonfigurasi. Hubungi admin.",
        "dep_idr_gopay_title": "💳 <b>Deposit IDR — QRIS All Payment</b>\n\nMinimum deposit: <b>{min}</b>\n\nKetik jumlah deposit yang Anda inginkan. Sistem akan membuat QR dengan nominal unik untuk pembayaran Anda.",
        "gopay_qr_created": "💳 <b>QRIS All Payment</b>\n\nDeposit: <b>{amount}</b>\nBiaya admin 0,7%: <b>{fee}</b>\nKode unik: <b>{platform_code}</b>\nTotal yang dibayarkan: <b>{payment_amount}</b>\n\nCara bayar: pindai QR melalui aplikasi e-wallet atau mobile banking yang mendukung QRIS. Saldo ditambahkan setelah pembayaran terverifikasi.\n⏳ QR hanya berlaku {expires} menit.",
        "gopay_deposit_confirm": "💳 <b>Konfirmasi Deposit</b>\n\nDeposit: <b>{amount}</b>\nAdmin fee 0.7% = deposit × 0.7%: <b>{fee}</b>\nAdmin platform: <b>{platform_code}</b>\nTotal yang dibayarkan: <b>{total}</b>\n\n⚠️ Sebelum melanjutkan, pastikan Anda memahami bahwa total pembayaran sudah termasuk admin fee 0.7% dan admin platform.\n\nLanjut generate QR?",
        "btn_deposit_agree": "✅ Setuju & Buat QR",
        "btn_deposit_cancel": "❌ Tidak, Batalkan",
        "gopay_confirm_button": "Pilih tombol <b>Setuju & Buat QR</b> atau <b>Tidak, Batalkan</b> untuk melanjutkan.",
        "gopay_unavailable": "⚠️ Sistem pembayaran QRIS sedang tidak tersedia. Silakan coba lagi nanti atau hubungi admin.",
        "dep_idr_gopay_title": "💳 <b>IDR Deposit — QRIS All Payment</b>\n\nMinimum deposit: <b>{min}</b>\n\nType the amount you want to deposit. The system will create a unique QR amount for your payment.",
        "gopay_qr_created": "💳 <b>QRIS All Payment</b>\n\nDeposit: <b>{amount}</b>\nAdmin fee 0.7%: <b>{fee}</b>\nUnique code: <b>{platform_code}</b>\nTotal payment: <b>{payment_amount}</b>\n\nHow to pay: scan this QR with any e-wallet or mobile banking app that supports QRIS. Your balance is credited after verification.\n⏳ QR is valid for {expires} minutes.",
        "gopay_deposit_confirm": "💳 <b>Deposit Confirmation</b>\n\nDeposit: <b>{amount}</b>\nAdmin fee 0.7% = deposit × 0.7%: <b>{fee}</b>\nPlatform code: <b>{platform_code}</b>\nTotal payment: <b>{total}</b>\n\n⚠️ The total payment already includes the 0.7% admin fee and platform code.\n\nContinue and generate the QR?",
        "btn_deposit_agree": "✅ Agree & Create QR",
        "btn_deposit_cancel": "❌ No, Cancel",
        "gopay_confirm_button": "Choose <b>Agree & Create QR</b> or <b>No, Cancel</b> to continue.",
        "gopay_unavailable": "⚠️ QRIS payment is temporarily unavailable. Please try again later or contact admin.",
        "dep_idr_title": "💰 <b>Deposit IDR — Transfer Bank</b>\n\n🏦 Bank: <b>{bank}</b>\n💳 No. Rekening: <code>{account}</code>\n👤 Atas Nama: <b>{holder}</b>\n\nMinimum deposit: <b>{min}</b>\n\nKetik <b>jumlah</b> yang akan Anda transfer (contoh: 100000):",
        "dep_no_address": "⚠️ Alamat deposit {coin} di jaringan {network} belum tersedia.\nSilakan pilih jaringan lain atau hubungi admin.",
        "dep_address": "💰 <b>Deposit {coin} — {network}</b>\n\nKirim {coin} Anda ke alamat berikut:\n\n<code>{address}</code>\n\n⚠️ <b>PENTING:</b>\n• Hanya kirim <b>{coin}</b> di jaringan <b>{network}</b>\n• Minimum deposit: <b>${min:,.2f}</b>\n\nSetelah transfer, ketik <b>jumlah deposit</b> Anda (contoh: 20):",
        "invalid_amount": "⚠️ Format jumlah tidak valid. Ketik angka saja:",
        "min_deposit": "⚠️ Jumlah minimum deposit adalah <b>{min}</b>. Ketik ulang jumlah:",
        "wallet_prompt": "👛 <b>Wallet pengirim</b>\n\nKirim alamat wallet yang Anda gunakan untuk mengirim transaksi ini di jaringan <b>{network}</b>. Wallet ini akan dicocokkan dengan TX hash untuk mencegah klaim transaksi milik orang lain.",
        "wallet_invalid": "⚠️ Format wallet tidak valid untuk jaringan ini. Kirim alamat wallet pengirim yang benar.",
        "wallet_prompt": "👛 <b>Sender wallet</b>\n\nSend the wallet address you used to send this transaction on <b>{network}</b>. It will be matched against the TX hash to prevent claiming someone else’s transaction.",
        "wallet_invalid": "⚠️ Invalid wallet format for this network. Send the correct sender wallet address.",
        "amount_set_usd": "👍 Jumlah deposit: <b>${amount:,.2f}</b>\n\nSekarang kirim <b>bukti transfer</b> Anda:\n\n🔗 <b>TX Hash</b> (disarankan) — saldo terverifikasi & masuk <b>otomatis</b>\n📷 <b>Screenshot</b> — diverifikasi manual oleh admin",
        "amount_set_idr": "👍 Jumlah deposit: <b>{amount}</b>\n\nSekarang kirim <b>foto bukti transfer</b> Anda di chat ini:",
        "proof_received": "⏳ <b>Deposit Menunggu Verifikasi</b>\n\nBukti Anda telah diterima. Admin akan memverifikasi secepatnya dan saldo akan masuk otomatis setelah disetujui.",
        "send_photo_please": "⚠️ Silakan kirim <b>foto</b> bukti transfer bank Anda:",
        "invalid_txhash": "⚠️ Format TX hash tidak valid.\n\nKirim <b>TX hash</b> transaksi Anda, atau kirim <b>screenshot</b> bukti transfer:",
        "tx_used": "⚠️ TX hash ini sudah pernah digunakan. Setiap transaksi hanya bisa diklaim satu kali.",
        "checking": "🔍 Memeriksa transaksi di blockchain, mohon tunggu...",
        "auto_ok": "✅ <b>Deposit Terverifikasi Otomatis!</b>\n\nTransaksi ditemukan di blockchain:\n• Koin: {coin} ({network})\n• Jumlah on-chain: <b>${amount:,.2f}</b>\n\nSaldo Anda sekarang: <b>${balance:,.2f}</b> 🎉",
        "pending_manual": "⏳ <b>Deposit Menunggu Verifikasi Manual</b>\n\nVerifikasi otomatis tidak berhasil: {reason}.\nAdmin akan memeriksa deposit Anda secepatnya.",
        "balance_view": "💳 <b>Saldo Anda</b>\n\n💵 USD: <b>${usd:,.2f}</b>\n🇮🇩 IDR: <b>{idr}</b>\n\nMata uang aktif: <b>{cur}</b>\nKurs saat ini: $1 = {rate}",
        "hist_header": "📜 <b>Riwayat Anda</b>\n", "hist_deposits": "<b>Deposit terakhir:</b>",
        "hist_purchases": "\n<b>Pembelian terakhir:</b>", "hist_none_dep": "Belum ada deposit.", "hist_none_pur": "Belum ada pembelian.",
        "hist_orders_title": "📦 <b>Detail Transaksi</b>", "hist_deposit_detail": "💰 <b>Detail Deposit</b>", "hist_order_detail": "🧾 <b>Detail Invoice</b>", "hist_open": "🔎 Lihat Detail", "hist_back": "◀️ Kembali ke Riwayat",
        "st_pending": "⏳ Menunggu", "st_approved": "✅ Disetujui", "st_rejected": "❌ Ditolak", "st_cancelled": "🚫 Dibatalkan",
        "settings_title": "⚙️ <b>Pengaturan</b>\n\nMata uang aktif: <b>{cur}</b>\nBahasa: <b>{lang}</b>",
        "choose_language": "🌐 <b>Pilih Bahasa / Choose Language</b>",
        "lang_set": "✅ Bahasa diubah ke <b>Indonesia</b>.",
        "currency_changed": "✅ Mata uang diubah ke <b>{cur}</b>.",
        "convert_ask": "🔄 <b>Ganti Mata Uang ke {cur}</b>\n\nAnda punya saldo <b>{balance}</b>.\nKonversi ke <b>{converted}</b> (kurs $1 = {rate})?",
        "converted_done": "✅ Mata uang diubah ke <b>{cur}</b> dan saldo dikonversi menjadi <b>{amount}</b>.",
        "changed_kept": "✅ Mata uang diubah ke <b>{cur}</b>. Saldo lama tetap tersimpan terpisah.",
        "frozen": "🚫 <b>Akun Anda Dibekukan</b>\n\n{reason}Anda tidak dapat melakukan deposit atau pembelian. Hubungi admin untuk informasi lebih lanjut.",
        "frozen_reason": "Alasan: {r}\n\n",
        "help": "❓ <b>Bantuan</b>\n\n<b>Cara belanja:</b>\n1️⃣ Isi saldo lewat menu <b>Deposit</b>\n2️⃣ Pilih produk di <b>Lihat Produk</b>\n3️⃣ Beli langsung atau lewat <b>Keranjang</b>\n4️⃣ Produk terkirim otomatis ✨\n\n<b>Perintah:</b>\n/start — mulai bot\n/menu — menu utama\n/saldo — cek saldo\n/riwayat — riwayat transaksi\n/batal — batalkan proses",
        "dep_approved": "✅ <b>Deposit Disetujui!</b>\n\nSaldo Anda bertambah <b>{amount}</b>.\nKetik /menu untuk mulai belanja.",
        "dep_rejected": "❌ <b>Deposit Ditolak</b>\n\nDeposit {amount} Anda ditolak.{reason}\nHubungi admin jika ada pertanyaan.",
        "dep_cancelled": "⚠️ <b>Deposit Dibatalkan Admin</b>\n\nDeposit {amount} dibatalkan dan saldo dikurangi kembali.",
        "adj_notice": "ℹ️ <b>Penyesuaian Saldo oleh Admin</b>\n\nSaldo Anda disesuaikan: <b>{amount}</b>{reason}",
        "frozen_notice": "🚫 <b>Akun Anda Dibekukan</b>{reason}\n\nSaldo terkunci dan Anda tidak dapat bertransaksi. Hubungi admin untuk info lebih lanjut.",
        "unfrozen_notice": "✅ <b>Akun Anda Telah Dibuka Kembali</b>\n\nAnda bisa bertransaksi seperti biasa. Ketik /menu untuk mulai.",
        "reason_label": "\nAlasan: {r}",
    },
    "en": {
        "choose_currency": "🏪 <b>Welcome to the Digital Product Store!</b>\n\nPlease choose your preferred currency:\n\n💵 <b>USD</b> — deposit via crypto (USDT/USDC)\n🇮🇩 <b>IDR</b> — deposit via bank transfer\n\nYou can change this anytime in Settings.",
        "main_title": "🏪 <b>Digital Product Store</b>\n\nHello, {name}! 👋\nYour balance: <b>{balance}</b>\n\nPlease choose a menu:",
        "btn_products": "📚 Product Catalogs", "btn_cart": "🛒 Cart", "btn_deposit": "💰 Deposit",
        "btn_balance": "💳 My Balance", "btn_history": "📜 History", "btn_settings": "⚙️ Settings",
        "btn_help": "❓ Help", "btn_stock": "📦 Stock", "btn_main": "🏠 Main Menu", "btn_back": "◀️ Back",
        "btn_cancel": "❌ Cancel", "btn_buy": "🛒 Buy Now ({price})", "btn_add_cart": "➕ Add to Cart",
        "btn_view_cart": "🛒 View Cart", "btn_continue": "🛍 Continue Shopping",
        "btn_checkout": "✅ Checkout ({total})", "btn_clear": "🧹 Clear Cart", "btn_deposit_now": "💰 Deposit Now",
        "btn_change_currency": "🔄 Switch to {cur}", "btn_language": "🌐 Bahasa / Language",
        "btn_convert_yes": "✅ Yes, convert balance", "btn_convert_no": "❌ No, keep balances separate",
        "btn_menu_short": "🏠 Menu", "btn_other_network": "◀️ Choose Another Network", "btn_remove": "🗑 Remove",
        "products_title": "🛍 <b>Product List</b>\n\nTap a product to view details:",
        "no_products": "🛍 <b>Products</b>\n\nNo products available at the moment.",
        "product_not_found": "Product not found.",
        "prod_detail": "📦 <b>{name}</b>\n\n{desc}\n\nType: {type}\nPrice: <b>{price}</b>\nStock available: <b>{stock}</b>",
        "type_file": "📁 File", "type_link": "🔗 Link", "type_license": "🔑 License Key", "type_inventory": "👤 Account / Inventory",
        "stock_word": "stock", "out_of_stock": "❌ <b>Out of stock</b> — this product is currently unavailable.",
        "stock_title": "📦 <b>Available Product Stock</b>\n",
        "stock_empty": "No products yet.",
        "stock_legend": (
            "\n🎨 Button colors show <b>stock availability</b> (not product condition):\n"
            "🔴 Red: stock 1–4 (almost out)\n"
            "🟢 Green: stock 5–9\n"
            "🔵 Blue: stock 10 and up"
        ),
        "added_cart": "✅ Product added to cart!",
        "qty_max": "⚠️ Quantity exceeds available stock ({stock}).",
        "cart_empty": "🛒 <b>Cart</b>\n\nYour cart is empty.",
        "cart_title": "🛒 <b>Your Cart</b>\n\nUse ➖ ➕ buttons to change quantity:",
        "cart_total": "Total: <b>{total}</b>",
        "cart_cleared": "🧹 Cart cleared.",
        "no_valid_products": "No valid products to purchase.",
        "insufficient": "⚠️ <b>Insufficient Balance</b>\n\nOrder total: <b>{total}</b>\nYour balance: {balance}\nShortfall: <b>{short}</b>\n\nPlease deposit first.",
        "stock_insufficient": "⚠️ Not enough stock for <b>{name}</b> ({stock} left). Adjust quantity in your cart.",
        "pay_success": "✅ <b>Payment Successful!</b>\n\nTotal: <b>{total}</b>\nDelivering your products...",
        "delivered_all": "🎉 All products delivered!\nRemaining balance: <b>{balance}</b>",
        "deliver_fail": "⚠️ Failed to send file <b>{name}</b>. Please contact admin.",
        "order_refunded": "💸 <b>Order Refunded</b>\n\nInvoice <code>{invoice}</code> was refunded for <b>{amount}</b> and your balance has been restored.",
        "checkout_in_progress": "⏳ Your checkout is already being processed. Please wait for the previous checkout to finish.",
        "checkout_failed": "⚠️ Checkout failed. Your balance and stock were not changed. Please try again.",
        "delivery_attention": "⚠️ Invoice <code>{invoice}</code> was created, but one or more products could not be delivered. Contact admin.",
        "deliver_link": "📦 <b>{name}</b>\n\n🔗 Your product link:\n{content}",
        "deliver_license": "📦 <b>{name}</b>\n\n🔑 Your license key:\n<code>{content}</code>",
        "dep_usd_title": "💰 <b>USD Deposit</b>\n\nMinimum deposit: <b>${min:,.2f}</b>\n\nChoose a coin:",
        "choose_network": "💰 <b>{coin} Deposit</b>\n\nChoose a network:",
        "dep_no_bank": "💰 <b>IDR Deposit</b>\n\n⚠️ Bank account not configured yet. Contact admin.",
        "dep_idr_title": "💰 <b>IDR Deposit — Bank Transfer</b>\n\n🏦 Bank: <b>{bank}</b>\n💳 Account No: <code>{account}</code>\n👤 Account Name: <b>{holder}</b>\n\nMinimum deposit: <b>{min}</b>\n\nType the <b>amount</b> you will transfer (e.g. 100000):",
        "dep_no_address": "⚠️ {coin} deposit address on {network} is not available yet.\nPlease choose another network or contact admin.",
        "dep_address": "💰 <b>{coin} Deposit — {network}</b>\n\nSend your {coin} to this address:\n\n<code>{address}</code>\n\n⚠️ <b>IMPORTANT:</b>\n• Only send <b>{coin}</b> on the <b>{network}</b> network\n• Minimum deposit: <b>${min:,.2f}</b>\n\nAfter transferring, type your <b>deposit amount</b> (e.g. 20):",
        "invalid_amount": "⚠️ Invalid amount format. Type numbers only:",
        "min_deposit": "⚠️ Minimum deposit amount is <b>{min}</b>. Please re-type the amount:",
        "amount_set_usd": "👍 Deposit amount: <b>${amount:,.2f}</b>\n\nNow send your <b>payment proof</b>:\n\n🔗 <b>TX Hash</b> (recommended) — verified & credited <b>automatically</b>\n📷 <b>Screenshot</b> — verified manually by admin",
        "amount_set_idr": "👍 Deposit amount: <b>{amount}</b>\n\nNow send a <b>photo of your transfer receipt</b> in this chat:",
        "proof_received": "⏳ <b>Deposit Awaiting Verification</b>\n\nYour proof has been received. Admin will verify it shortly and your balance will be credited automatically once approved.",
        "send_photo_please": "⚠️ Please send a <b>photo</b> of your bank transfer receipt:",
        "invalid_txhash": "⚠️ Invalid TX hash format.\n\nSend your transaction <b>TX hash</b>, or send a <b>screenshot</b> of the transfer:",
        "tx_used": "⚠️ This TX hash has already been used. Each transaction can only be claimed once.",
        "checking": "🔍 Checking the transaction on-chain, please wait...",
        "auto_ok": "✅ <b>Deposit Auto-Verified!</b>\n\nTransaction found on-chain:\n• Coin: {coin} ({network})\n• On-chain amount: <b>${amount:,.2f}</b>\n\nYour balance is now: <b>${balance:,.2f}</b> 🎉",
        "pending_manual": "⏳ <b>Deposit Awaiting Manual Verification</b>\n\nAutomatic verification failed: {reason}.\nAdmin will review your deposit shortly.",
        "balance_view": "💳 <b>Your Balance</b>\n\n💵 USD: <b>${usd:,.2f}</b>\n🇮🇩 IDR: <b>{idr}</b>\n\nActive currency: <b>{cur}</b>\nCurrent rate: $1 = {rate}",
        "hist_header": "📜 <b>Your History</b>\n", "hist_deposits": "<b>Recent deposits:</b>",
        "hist_purchases": "\n<b>Recent purchases:</b>", "hist_none_dep": "No deposits yet.", "hist_none_pur": "No purchases yet.",
        "hist_orders_title": "📦 <b>Transaction Details</b>", "hist_deposit_detail": "💰 <b>Deposit Details</b>", "hist_order_detail": "🧾 <b>Invoice Details</b>", "hist_open": "🔎 View Details", "hist_back": "◀️ Back to History",
        "st_pending": "⏳ Pending", "st_approved": "✅ Approved", "st_rejected": "❌ Rejected", "st_cancelled": "🚫 Cancelled",
        "settings_title": "⚙️ <b>Settings</b>\n\nActive currency: <b>{cur}</b>\nLanguage: <b>{lang}</b>",
        "choose_language": "🌐 <b>Pilih Bahasa / Choose Language</b>",
        "lang_set": "✅ Language changed to <b>English</b>.",
        "currency_changed": "✅ Currency changed to <b>{cur}</b>.",
        "convert_ask": "🔄 <b>Switch Currency to {cur}</b>\n\nYou have a balance of <b>{balance}</b>.\nConvert it to <b>{converted}</b> (rate $1 = {rate})?",
        "converted_done": "✅ Currency changed to <b>{cur}</b> and balance converted to <b>{amount}</b>.",
        "changed_kept": "✅ Currency changed to <b>{cur}</b>. Your old balance is kept separately.",
        "frozen": "🚫 <b>Your Account Is Frozen</b>\n\n{reason}You cannot deposit or purchase. Contact admin for more information.",
        "frozen_reason": "Reason: {r}\n\n",
        "help": "❓ <b>Help</b>\n\n<b>How to shop:</b>\n1️⃣ Top up via the <b>Deposit</b> menu\n2️⃣ Pick a product in <b>Browse Products</b>\n3️⃣ Buy directly or via <b>Cart</b>\n4️⃣ Products are delivered automatically ✨\n\n<b>Commands:</b>\n/start — start bot\n/menu — main menu\n/saldo — check balance\n/riwayat — transaction history\n/batal — cancel process",
        "dep_approved": "✅ <b>Deposit Approved!</b>\n\nYour balance increased by <b>{amount}</b>.\nType /menu to start shopping.",
        "dep_rejected": "❌ <b>Deposit Rejected</b>\n\nYour {amount} deposit was rejected.{reason}\nContact admin if you have questions.",
        "dep_cancelled": "⚠️ <b>Deposit Cancelled by Admin</b>\n\nThe {amount} deposit was cancelled and deducted from your balance.",
        "adj_notice": "ℹ️ <b>Balance Adjustment by Admin</b>\n\nYour balance was adjusted: <b>{amount}</b>{reason}",
        "frozen_notice": "🚫 <b>Your Account Is Frozen</b>{reason}\n\nYour balance is locked and you cannot transact. Contact admin for more info.",
        "unfrozen_notice": "✅ <b>Your Account Has Been Unfrozen</b>\n\nYou can transact as usual. Type /menu to start.",
        "reason_label": "\nReason: {r}",
    },
}

# Admin payment gateway selection messages are kept here so they can be overridden
# through the existing bot-message editor later.
STRINGS["id"].update({
    "dep_idr_method_title": "💰 <b>Pilih Metode Deposit IDR</b>\n\nPilih metode pembayaran yang tersedia:",
    "btn_gopay_qris": "📱 QRIS +0.7% otomatis",
    "btn_bank_transfer": "🏦 Bank Transfer 0 fees — manual checking",
    "dep_gateway_offline": "⚠️ <b>Maaf, sedang ada gangguan pada gateway payment/bank kami.</b>\n\nSilakan coba lagi nanti.",
})
STRINGS["en"].update({
    "dep_idr_method_title": "💰 <b>Choose IDR Deposit Method</b>\n\nChoose an available payment method:",
    "btn_gopay_qris": "📱 QRIS +0.7% automatic",
    "btn_bank_transfer": "🏦 Bank Transfer 0 fees — manual checking",
    "dep_gateway_offline": "⚠️ <b>Sorry, our payment/bank gateway is currently unavailable.</b>\n\nPlease try again later.",
})

LANG_NAMES = {"id": "🇮🇩 Indonesia", "en": "🇬🇧 English"}

OVERRIDES = {}


async def load_overrides(collection):
    OVERRIDES.clear()
    cursor = collection.find({"active": {"$ne": False}})
    async for row in cursor:
        OVERRIDES[(row.get("lang", "id"), row.get("key"))] = row.get("text", "")


def set_override(lang, key, value):
    OVERRIDES[(lang, key)] = value


def reset_override(lang, key):
    OVERRIDES.pop((lang, key), None)


def message_catalog():
    keys = sorted(set(STRINGS["id"]) | set(STRINGS["en"]))
    return keys


def t(_lang: str, key: str, **kw) -> str:
    _lang = _lang if _lang in STRINGS else "id"
    s = OVERRIDES.get((_lang, key))
    if s is None:
        s = STRINGS[_lang].get(key) or STRINGS["id"].get(key, key)
    return s.format(**kw) if kw else s
