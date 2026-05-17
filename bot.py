import os
import re
import logging
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("finance-bot")

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ─── SUMBER UANG ──────────────────────────────────────────────────────────────
# Semua kemungkinan penulisan → nama resmi
SUMBER_MAP = {
    # Cash
    "cash": "Cash", "tunai": "Cash", "uang": "Cash",
    # GoPay
    "gopay": "GoPay", "go pay": "GoPay", "gp": "GoPay",
    # Dana
    "dana": "Dana",
    # ShopeePay
    "shopeepay": "ShopeePay", "shopee": "ShopeePay",
    "spay": "ShopeePay", "s pay": "ShopeePay", "shoppe": "ShopeePay",
    # OVO
    "ovo": "OVO",
    # Rekening (semua bank → 1 rekening)
    "rekening": "Rekening", "rek": "Rekening",
    "bca": "Rekening", "bri": "Rekening", "mandiri": "Rekening",
    "bni": "Rekening", "jago": "Rekening", "seabank": "Rekening",
    "jenius": "Rekening", "bank": "Rekening",
}

# Sumber yang ditampilkan di dashboard
SUMBER_EWALLET = ["GoPay", "Dana", "ShopeePay", "OVO"]
SUMBER_LIST_TEXT = "Cash · Rekening · GoPay · Dana · ShopeePay · OVO"

# ─── KATEGORI ─────────────────────────────────────────────────────────────────
KATEGORI_KELUAR = {
    "makan":"Makanan & Minuman","minum":"Makanan & Minuman","kopi":"Makanan & Minuman",
    "resto":"Makanan & Minuman","warung":"Makanan & Minuman","lunch":"Makanan & Minuman",
    "dinner":"Makanan & Minuman","sarapan":"Makanan & Minuman","bakso":"Makanan & Minuman",
    "nasi":"Makanan & Minuman","jajan":"Makanan & Minuman","snack":"Makanan & Minuman",
    "mie":"Makanan & Minuman","ayam":"Makanan & Minuman","soto":"Makanan & Minuman",
    "transport":"Transportasi","bensin":"Transportasi","grab":"Transportasi",
    "gojek":"Transportasi","ojek":"Transportasi","parkir":"Transportasi",
    "toll":"Transportasi","tol":"Transportasi","bis":"Transportasi","kereta":"Transportasi",
    "motor":"Transportasi","servis":"Transportasi",
    "listrik":"Tagihan","air":"Tagihan","internet":"Tagihan","pulsa":"Tagihan",
    "tagihan":"Tagihan","token":"Tagihan","iuran":"Tagihan","wifi":"Tagihan",
    "pdam":"Tagihan","pln":"Tagihan",
    "belanja":"Belanja","baju":"Belanja","sepatu":"Belanja","buku":"Belanja",
    "grocery":"Belanja","supermarket":"Belanja","indomaret":"Belanja","alfamart":"Belanja",
    "lazada":"Belanja","tokopedia":"Belanja","shopee":"Belanja",
    "hiburan":"Hiburan","nonton":"Hiburan","game":"Hiburan","netflix":"Hiburan",
    "spotify":"Hiburan","youtube":"Hiburan","bioskop":"Hiburan","main":"Hiburan",
    "obat":"Kesehatan","dokter":"Kesehatan","apotek":"Kesehatan",
    "vitamin":"Kesehatan","gym":"Kesehatan","klinik":"Kesehatan","rumah sakit":"Kesehatan",
    "transfer":"Transfer","kirim":"Transfer",
    "topup":"Top Up","isi":"Top Up","top up":"Top Up",
    "kos":"Tempat Tinggal","kontrakan":"Tempat Tinggal","sewa":"Tempat Tinggal","rent":"Tempat Tinggal",
}
KATEGORI_MASUK = {
    "gaji":"Gaji","salary":"Gaji","upah":"Gaji","slip":"Gaji",
    "freelance":"Freelance","proyek":"Freelance","project":"Freelance","kerja":"Freelance",
    "bisnis":"Bisnis","jualan":"Bisnis","usaha":"Bisnis","dagang":"Bisnis",
    "bonus":"Bonus","thr":"Bonus","reward":"Bonus",
    "investasi":"Investasi","dividen":"Investasi","bunga":"Investasi","saham":"Investasi",
    "transfer":"Transfer Masuk","kiriman":"Transfer Masuk","kirim":"Transfer Masuk",
    "cashback":"Cashback","refund":"Refund","kembali":"Refund",
}

# ─── PARSE NOMINAL ────────────────────────────────────────────────────────────
def parse_nominal(raw: str) -> float:
    raw = raw.lower().strip().replace(",", ".").replace(" ", "")
    mult = 1
    if raw.endswith("jt") or raw.endswith("juta"):
        mult = 1_000_000
        raw = re.sub(r"(jt|juta)$", "", raw)
    elif raw.endswith("rb") or raw.endswith("ribu"):
        mult = 1_000
        raw = re.sub(r"(rb|ribu)$", "", raw)
    elif raw.endswith("k"):
        mult = 1_000
        raw = raw[:-1]
    try:
        return float(raw) * mult
    except ValueError:
        return 0

def find_nominal(text: str) -> float:
    hits = re.findall(r"\d+(?:[.,]\d+)?(?:k|rb|ribu|jt|juta)?", text.lower())
    for h in reversed(hits):
        n = parse_nominal(h)
        if n > 0:
            return n
    return 0

def find_sumber(text: str) -> str | None:
    t = text.lower().strip()
    # Coba multi-kata dulu (misal "go pay", "s pay")
    for kw, val in sorted(SUMBER_MAP.items(), key=lambda x: -len(x[0])):
        if kw in t:
            return val
    return None

def find_kategori(text: str, tipe: str) -> str:
    t = text.lower()
    mapping = KATEGORI_KELUAR if tipe == "Pengeluaran" else KATEGORI_MASUK
    for kw, kat in mapping.items():
        if kw in t:
            return kat
    return "Lainnya" if tipe == "Pengeluaran" else "Pendapatan Lain"

def buat_deskripsi(rest: str) -> str:
    t = rest.lower()
    for k in SUMBER_MAP:
        t = re.sub(rf"\b{re.escape(k)}\b", "", t)
    t = re.sub(r"\d+(?:[.,]\d+)?(?:k|rb|ribu|jt|juta)?", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -_/")
    return t.title() if t.strip() else "Transaksi"

# ─── PARSE COMMAND ────────────────────────────────────────────────────────────
def parse_command(text: str) -> dict:
    lower = text.lower().strip()
    if lower.startswith("/masuk"):
        tipe, rest = "Pemasukan", text[6:].strip()
    elif lower.startswith("/keluar"):
        tipe, rest = "Pengeluaran", text[7:].strip()
    elif lower.startswith("/tabung"):
        tipe, rest = "Tabungan", text[7:].strip()
    else:
        return {"error": "unknown"}

    if not rest:
        return {"error": "kosong", "tipe": tipe}

    nominal = find_nominal(rest)
    if nominal <= 0:
        return {"error": "no_nominal", "tipe": tipe}

    if tipe == "Tabungan":
        deskripsi = buat_deskripsi(rest) or "Tabungan"
        sumber, kategori = "Tabungan", "Tabungan"
    else:
        sumber = find_sumber(rest)
        if not sumber:
            return {"error": "no_sumber", "tipe": tipe}
        kategori = find_kategori(rest, tipe)
        deskripsi = buat_deskripsi(rest) or "Transaksi"

    now = datetime.now()
    return {
        "tanggal": now.strftime("%d/%m/%Y"),
        "bulan": now.strftime("%B"),
        "tahun": now.year,
        "deskripsi": deskripsi,
        "kategori": kategori,
        "tipe": tipe,
        "sumber": sumber,
        "nominal": nominal,
    }

# ─── SHEETS API ───────────────────────────────────────────────────────────────
def post_sheets(data: dict) -> dict:
    """POST ke Apps Script. Auto-retry 1x kalau timeout (cold start)."""
    if not GOOGLE_SCRIPT_URL:
        log.error("GOOGLE_SCRIPT_URL tidak diset!")
        return {"status": "error", "message": "url_kosong"}

    log.info(f"POST sheets payload: {data}")

    for attempt in (1, 2):
        try:
            r = requests.post(
                GOOGLE_SCRIPT_URL,
                json=data,
                timeout=30,
                allow_redirects=True,
            )
            log.info(f"POST attempt {attempt} status={r.status_code} body={r.text[:300]}")
            try:
                return r.json()
            except ValueError:
                # response bukan JSON (biasanya HTML error dari Google)
                return {
                    "status": "error",
                    "message": f"non_json (http {r.status_code}): {r.text[:200]}",
                }
        except requests.Timeout:
            log.warning(f"POST attempt {attempt} TIMEOUT")
            if attempt == 2:
                return {"status": "error", "message": "timeout"}
        except Exception as e:
            log.exception(f"POST attempt {attempt} error: {e}")
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "unknown"}

def get_sheets(action: str) -> dict:
    try:
        r = requests.get(
            f"{GOOGLE_SCRIPT_URL}?action={action}",
            timeout=30,
            allow_redirects=True,
        )
        log.info(f"GET {action} status={r.status_code} body={r.text[:200]}")
        return r.json()
    except Exception as e:
        log.exception(f"GET {action} error: {e}")
        return {"status": "error"}

def get_sheets_saldo(sumber: str) -> dict:
    try:
        r = requests.get(
            f"{GOOGLE_SCRIPT_URL}?action=saldo_sumber&sumber={sumber}",
            timeout=30,
            allow_redirects=True,
        )
        log.info(f"GET saldo_sumber={sumber} status={r.status_code} body={r.text[:200]}")
        return r.json()
    except Exception as e:
        log.exception(f"GET saldo_sumber error: {e}")
        return {"status": "error"}

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send(chat_id: int, text: str) -> int | None:
    """Kirim pesan ke Telegram, return message_id biar bisa di-edit nanti."""
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
        }, timeout=10)
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.exception(f"send error: {e}")
        return None

def edit(chat_id: int, message_id: int, text: str):
    """Edit pesan yang udah dikirim. Dipakai buat update '⏳ Mencatat...' jadi hasil akhir."""
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        log.exception(f"edit error: {e}")

def fmt(n: float) -> str:
    return f"Rp {int(n):,}".replace(",", ".")

# ─── TEKS HELP ────────────────────────────────────────────────────────────────
def get_help(nama: str) -> str:
    return f"""Halo *{nama}*! 👋

💰 *Catatan Keuangan Otomatis*

🚨 *PENTING\\! BACA FORMAT SEBELUM LANJUT* 🚨

Gunakan command berikut:
💵 /masuk → untuk uang masuk
💸 /keluar → untuk uang keluar
🏦 /tabung → untuk uang yang ditabung

Bot ini juga bisa *melacak asal uang masuk & keluar* kamu, seperti:
💳 E\\-Wallet
💵 Cash/Tunai
🏦 Rekening Pribadi

📌 *FORMAT WAJIB:*
`/command (asal dana) nominal`

✨ *Contoh penggunaan:*
`/keluar Gopay 10k`
`/tabung 10k`
`/masuk Spay 20k`
`/keluar Gopay makan 10k`
`/masuk Rekening 5jt gaji`
`/keluar Cash 15k transport`

🤖 *COMMAND KHUSUS BOT*
❌ /gajadi → Menghapus *1 transaksi terakhir* yang salah input
🔄 /refresh → Refresh dashboard kamu
💰 /saldo → Melihat total saldo
💳 /saldo gopay → Melihat saldo E\\-Wallet tertentu
📅 /bulan → Ringkasan keuangan bulan ini
❓ /help → Menampilkan menu ini
⚠️ /reset → *MENGHAPUS SELURUH TRANSAKSI*

💳 *Sumber uang yang dikenali:*
`Cash` / `Tunai`
`Rekening` / `Rek` / `BCA` / `BRI` / `Mandiri`
`GoPay` / `Gopay` / `GP`
`Dana`
`ShopeePay` / `Shopee` / `SPay` / `Spay`
`OVO`

📂 *Kategori Otomatis*
🍔 Makanan & Minuman
🚗 Transportasi
💡 Tagihan
🛍️ Belanja
🎬 Hiburan
💊 Kesehatan
💼 Gaji
💰 Freelance
🏦 Tabungan"""

# ─── STATE /reset konfirmasi ───────────────────────────────────────────────────
reset_pending = set()  # simpan chat_id yang sudah ketik /reset pertama

# ─── WEBHOOK ──────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"ok": True})

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    nama = msg["from"].get("first_name", "kamu")
    text = msg.get("text", "").strip()
    log.info(f"INCOMING chat_id={chat_id} nama={nama} text={text!r}")
    if not text:
        return jsonify({"ok": True})

    lower = text.lower()

    # ── /start ──
    if lower == "/start":
        send(chat_id, get_help(nama))
        return jsonify({"ok": True})

    # ── /help ──
    if lower in ["/help", "/bantuan"]:
        send(chat_id, get_help(nama))
        return jsonify({"ok": True})

    # ── /saldo [sumber opsional] ──
    if lower.startswith("/saldo"):
        parts = lower.split()
        if len(parts) >= 2:
            # /saldo gopay, /saldo dana, dll
            keyword = parts[1]
            sumber = find_sumber(keyword)
            if sumber:
                r = get_sheets_saldo(sumber)
                if r.get("status") == "ok":
                    d = r["data"]
                    send(chat_id, f"""💳 *Saldo {sumber}*

💚 Masuk:  {fmt(d.get('masuk', 0))}
🔴 Keluar: {fmt(d.get('keluar', 0))}
✅ Saldo:  *{fmt(d.get('saldo', 0))}*

📝 Total transaksi: {d.get('total_tx', 0)}""")
                else:
                    send(chat_id, f"❌ Gagal ambil saldo {sumber}.")
            else:
                send(chat_id, f"❓ Sumber *{parts[1]}* tidak dikenali.\n\nCoba: `/saldo gopay`, `/saldo dana`, `/saldo cash`")
        else:
            # /saldo → ringkasan keseluruhan
            r = get_sheets("summary")
            if r.get("status") == "ok":
                d = r["data"]
                icon = "✅" if d.get("saldo", 0) >= 0 else "⚠️"
                teks = f"""📊 *Ringkasan {d.get('bulan')} {d.get('tahun')}*

💚 Total Pemasukan:   *{fmt(d.get('pemasukan',0))}*
🔴 Total Pengeluaran: *{fmt(d.get('pengeluaran',0))}*
{icon} Saldo Aktif:      *{fmt(d.get('saldo',0))}*
🏦 Total Tabungan:    *{fmt(d.get('tabungan',0))}*

━━━━━━━━━━━━━━━
💵 Cash:      {fmt(d.get('cash',0))}
🏦 Rekening:  {fmt(d.get('rekening',0))}
🟢 GoPay:     {fmt(d.get('gopay',0))}
🔵 Dana:      {fmt(d.get('dana',0))}
🟠 ShopeePay: {fmt(d.get('shopeepay',0))}
🟣 OVO:       {fmt(d.get('ovo',0))}

📝 Total transaksi: {d.get('total_tx',0)}
🕐 {d.get('updated','-')}"""
                send(chat_id, teks)
            else:
                send(chat_id, "❌ Gagal ambil data, coba lagi ya.")
        return jsonify({"ok": True})

    # ── /bulan ──
    if lower == "/bulan":
        r = get_sheets("bulan")
        if r.get("status") == "ok":
            d = r["data"]
            icon = "✅" if d.get("saldo", 0) >= 0 else "⚠️"
            send(chat_id, f"""📅 *Ringkasan Bulan {d.get('bulan')} {d.get('tahun')}*

💚 Pemasukan:   *{fmt(d.get('pemasukan',0))}*
🔴 Pengeluaran: *{fmt(d.get('pengeluaran',0))}*
{icon} Saldo:       *{fmt(d.get('saldo',0))}*
🏦 Tabungan:    *{fmt(d.get('tabungan',0))}*

📝 Transaksi bulan ini: {d.get('total_tx',0)}""")
        else:
            send(chat_id, "❌ Gagal ambil data.")
        return jsonify({"ok": True})

    # ── /refresh ──
    if lower == "/refresh":
        send(chat_id, "🔄 Sedang refresh dashboard...")
        r = get_sheets("refresh")
        if r.get("status") == "ok":
            send(chat_id, "✅ Dashboard berhasil direfresh!\n\nBuka Google Sheets untuk melihat tampilan terbaru.")
        else:
            send(chat_id, "❌ Gagal refresh. Coba lagi ya.")
        return jsonify({"ok": True})

    # ── /gajadi ──
    if lower in ["/gajadi", "/batal"]:
        r = get_sheets("delete_last")
        if r.get("status") == "ok":
            d = r.get("data", {})
            send(chat_id, f"""🗑️ *Transaksi terakhir dihapus!*

_{d.get('deskripsi','?')} · {fmt(d.get('nominal',0))} · {d.get('tanggal','?')}_

Transaksi sudah dihapus dari catatan.
Dashboard akan terupdate otomatis.""")
        elif r.get("status") == "empty":
            send(chat_id, "Tidak ada transaksi yang bisa dihapus.")
        else:
            send(chat_id, "❌ Gagal hapus, coba lagi.")
        return jsonify({"ok": True})

    # ── /reset ──
    if lower == "/reset":
        reset_pending.add(chat_id)
        send(chat_id, """⚠️ *PERINGATAN KERAS!*

Kamu akan menghapus *SELURUH DATA TRANSAKSI* yang pernah dicatat.

Data yang dihapus *tidak bisa dikembalikan!*

Kalau yakin, ketik:
`/reset konfirmasi`

Kalau tidak jadi, abaikan pesan ini.""")
        return jsonify({"ok": True})

    if lower == "/reset konfirmasi":
        if chat_id in reset_pending:
            reset_pending.discard(chat_id)
            r = get_sheets("reset")
            if r.get("status") == "ok":
                send(chat_id, "✅ Semua transaksi telah dihapus.\n\nCatatan keuangan kamu sekarang kosong.")
            else:
                send(chat_id, "❌ Gagal reset. Coba lagi.")
        else:
            send(chat_id, "Ketik `/reset` dulu sebelum konfirmasi.")
        return jsonify({"ok": True})

    # ── /masuk /keluar /tabung ──
    if lower.startswith(("/masuk", "/keluar", "/tabung")):
        result = parse_command(text)
        err = result.get("error")
        tipe = result.get("tipe", "")

        if err == "kosong":
            contoh = {
                "Pemasukan": "`/masuk Gopay 5jt gaji`",
                "Pengeluaran": "`/keluar Cash 25k makan`",
                "Tabungan": "`/tabung 500k dana darurat`",
            }.get(tipe, "")
            send(chat_id, f"📝 Formatnya kurang lengkap nih.\n\nContoh: {contoh}\n\nKetik /help untuk panduan lengkap.")
            return jsonify({"ok": True})

        if err == "no_nominal":
            send(chat_id, "💵 Nominalnya belum ada nih!\n\nContoh:\n`/keluar Dana 25k`\n`/masuk BCA 2jt`\n`/tabung 300k`")
            return jsonify({"ok": True})

        if err == "no_sumber":
            cmd = "/masuk" if tipe == "Pemasukan" else "/keluar"
            send(chat_id, f"""Maaf, masukin detail dong dari mana, biar ga lupa! 🤔

Sertakan sumber dananya ya:
`{cmd} GoPay 50k`
`{cmd} Cash 25k`
`{cmd} Rekening 500k`

*Sumber yang tersedia:*
{SUMBER_LIST_TEXT}

Ketik /help untuk panduan lengkap.""")
            return jsonify({"ok": True})

        # Kirim ACK instan biar user tau bot udah terima command,
        # terus proses POST ke Sheets di background thread (handle cold start).
        ack_text = "⏳ Sedang mencatat ke Sheets...\n_(tunggu sebentar ya)_"
        message_id = send(chat_id, ack_text)

        def _save_and_reply():
            saved = post_sheets(result)
            if saved.get("status") == "ok":
                icon = {"Pemasukan": "💚", "Pengeluaran": "🔴", "Tabungan": "🏦"}.get(tipe, "📝")
                final = f"""{icon} *{tipe} tercatat!*

📝 {result['deskripsi']}
💳 Sumber: *{result['sumber']}*
🏷️ Kategori: {result['kategori']}
💵 {fmt(result['nominal'])}
📅 {result['tanggal']}

_Salah input? Ketik /gajadi_"""
            else:
                reason = saved.get("message", "")
                log.error(f"post_sheets gagal: {saved}")
                if reason == "timeout":
                    final = "⏱️ Server Sheets lambat merespon, tapi data *kemungkinan sudah masuk*.\n\nCek di Google Sheets ya. Kalau dobel, pakai /gajadi."
                elif reason == "url_kosong":
                    final = "❌ `GOOGLE_SCRIPT_URL` belum diset di environment variable."
                else:
                    final = f"❌ Gagal simpan ke Sheets.\n\n_Detail: {reason[:150]}_"

            if message_id:
                edit(chat_id, message_id, final)
            else:
                send(chat_id, final)

        threading.Thread(target=_save_and_reply, daemon=True).start()
        return jsonify({"ok": True})

    # ── Tidak dikenali ──
    send(chat_id, """❓ Aku kurang ngerti perintahnya.

Gunakan:
/masuk — catat uang masuk
/keluar — catat pengeluaran
/tabung — catat tabungan
/saldo — lihat ringkasan
/help — panduan lengkap""")
    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Finance Bot aktif ✅"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
