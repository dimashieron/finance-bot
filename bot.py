import os
import re
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ─── CATEGORY MAPPING ─────────────────────────────────────────────────────────
EXPENSE_KEYWORDS = {
    "makan": "Makanan & Minuman",
    "minum": "Makanan & Minuman",
    "kopi": "Makanan & Minuman",
    "resto": "Makanan & Minuman",
    "warung": "Makanan & Minuman",
    "lunch": "Makanan & Minuman",
    "dinner": "Makanan & Minuman",
    "sarapan": "Makanan & Minuman",
    "transport": "Transportasi",
    "bensin": "Transportasi",
    "grab": "Transportasi",
    "gojek": "Transportasi",
    "ojek": "Transportasi",
    "parkir": "Transportasi",
    "toll": "Transportasi",
    "listrik": "Tagihan & Utilitas",
    "air": "Tagihan & Utilitas",
    "internet": "Tagihan & Utilitas",
    "pulsa": "Tagihan & Utilitas",
    "tagihan": "Tagihan & Utilitas",
    "token": "Tagihan & Utilitas",
    "belanja": "Belanja",
    "baju": "Belanja",
    "sepatu": "Belanja",
    "buku": "Belanja",
    "alat": "Belanja",
    "hiburan": "Hiburan",
    "nonton": "Hiburan",
    "game": "Hiburan",
    "netflix": "Hiburan",
    "spotify": "Hiburan",
    "kesehatan": "Kesehatan",
    "obat": "Kesehatan",
    "dokter": "Kesehatan",
    "apotek": "Kesehatan",
}

INCOME_KEYWORDS = {
    "gaji": "Gaji",
    "salary": "Gaji",
    "upah": "Gaji",
    "freelance": "Freelance",
    "proyek": "Freelance",
    "project": "Freelance",
    "bisnis": "Bisnis",
    "jualan": "Bisnis",
    "bonus": "Bonus",
    "thr": "Bonus",
    "investasi": "Investasi",
    "dividen": "Investasi",
    "bunga": "Investasi",
}

SAVING_KEYWORDS = ["tabungan", "nabung", "saving", "simpan", "deposito"]

HELP_TEXT = """
💰 *Catatan Keuangan Otomatis*

*Format Input Sederhana:*
`makan 25000`
`gaji 5000000`
`transport 15000`
`tabungan 500000`

*Format Lengkap:*
`pengeluaran makan siang 25000`
`pemasukan gaji juni 5000000`
`tabungan darurat 500000`

*Perintah Khusus:*
/saldo — Lihat ringkasan bulan ini
/bulan — Ringkasan per bulan
/help — Tampilkan bantuan ini

*Kategori Otomatis:*
🍔 Makanan • 🚗 Transportasi • 💡 Tagihan
🛍️ Belanja • 🎬 Hiburan • 💊 Kesehatan
💼 Gaji • 💰 Freelance • 🏦 Tabungan
"""

# ─── PARSER ───────────────────────────────────────────────────────────────────
def parse_transaction(text: str) -> dict | None:
    text = text.strip().lower()
    
    # Detect amount (last number in message)
    numbers = re.findall(r'[\d.,]+(?:rb|ribu|jt|juta|k)?', text)
    if not numbers:
        return None
    
    raw_amount = numbers[-1]
    amount = parse_amount(raw_amount)
    if amount <= 0:
        return None
    
    # Remove amount from text for category detection
    desc_text = text.replace(raw_amount, "").strip()
    
    # Detect type
    tipe, kategori = detect_type_category(desc_text)
    
    # Clean description
    desc = clean_description(text, raw_amount)
    
    now = datetime.now()
    return {
        "tanggal": now.strftime("%d/%m/%Y"),
        "bulan": now.strftime("%B"),
        "tahun": now.year,
        "deskripsi": desc.title(),
        "kategori": kategori,
        "tipe": tipe,
        "nominal": amount,
    }

def parse_amount(raw: str) -> float:
    raw = raw.lower().replace(",", ".")
    multiplier = 1
    if raw.endswith("jt") or raw.endswith("juta"):
        multiplier = 1_000_000
        raw = re.sub(r'(jt|juta)$', '', raw)
    elif raw.endswith("rb") or raw.endswith("ribu") or raw.endswith("k"):
        multiplier = 1_000
        raw = re.sub(r'(rb|ribu|k)$', '', raw)
    try:
        return float(raw) * multiplier
    except ValueError:
        return 0

def detect_type_category(text: str) -> tuple[str, str]:
    # Explicit type keywords
    if any(k in text for k in ["pengeluaran", "bayar", "beli", "keluar"]):
        cat = detect_expense_category(text)
        return "Pengeluaran", cat
    if any(k in text for k in ["pemasukan", "terima", "dapat", "masuk"]):
        cat = detect_income_category(text)
        return "Pemasukan", cat
    if any(k in text for k in SAVING_KEYWORDS):
        return "Tabungan", "Tabungan"
    
    # Auto-detect by keyword
    for kw, cat in EXPENSE_KEYWORDS.items():
        if kw in text:
            return "Pengeluaran", cat
    for kw, cat in INCOME_KEYWORDS.items():
        if kw in text:
            return "Pemasukan", cat
    
    # Default: expense
    return "Pengeluaran", "Lainnya"

def detect_expense_category(text: str) -> str:
    for kw, cat in EXPENSE_KEYWORDS.items():
        if kw in text:
            return cat
    return "Lainnya"

def detect_income_category(text: str) -> str:
    for kw, cat in INCOME_KEYWORDS.items():
        if kw in text:
            return cat
    return "Pendapatan Lain"

def clean_description(text: str, amount_str: str) -> str:
    remove = ["pengeluaran", "pemasukan", "tabungan", "nabung",
              "bayar", "beli", amount_str]
    for r in remove:
        text = text.replace(r, "")
    # Remove numbers
    text = re.sub(r'\d+', '', text).strip()
    return text if text else "Transaksi"

# ─── SHEETS INTEGRATION ───────────────────────────────────────────────────────
def save_to_sheets(data: dict) -> bool:
    try:
        resp = requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=10)
        result = resp.json()
        return result.get("status") == "ok"
    except Exception as e:
        print(f"Sheets error: {e}")
        return False

def get_summary_from_sheets(chat_id: int) -> str:
    try:
        resp = requests.get(f"{GOOGLE_SCRIPT_URL}?action=summary", timeout=10)
        data = resp.json()
        if data.get("status") == "ok":
            d = data["data"]
            return format_summary(d)
    except Exception as e:
        print(f"Summary error: {e}")
    return "❌ Gagal mengambil data. Coba lagi."

def format_summary(d: dict) -> str:
    def fmt(n): return f"Rp {int(n):,}".replace(",", ".")
    saldo_emoji = "✅" if d.get("saldo", 0) >= 0 else "⚠️"
    return f"""
📊 *Ringkasan {d.get('bulan', 'Bulan Ini')} {d.get('tahun', '')}*

💚 Pemasukan: *{fmt(d.get('pemasukan', 0))}*
🔴 Pengeluaran: *{fmt(d.get('pengeluaran', 0))}*
{saldo_emoji} Saldo Aktif: *{fmt(d.get('saldo', 0))}*
🏦 Tabungan: *{fmt(d.get('tabungan', 0))}*

📝 Total Transaksi: {d.get('total_tx', 0)}
📅 Update: {d.get('updated', '-')}
""".strip()

# ─── TELEGRAM HELPERS ─────────────────────────────────────────────────────────
def send_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }, timeout=10)

def send_success(chat_id: int, tx: dict):
    icons = {"Pemasukan": "💚", "Pengeluaran": "🔴", "Tabungan": "🏦"}
    icon = icons.get(tx["tipe"], "📝")
    nominal = f"Rp {int(tx['nominal']):,}".replace(",", ".")
    msg = f"""{icon} *{tx['tipe']} Tercatat!*

📝 {tx['deskripsi']}
🏷️ {tx['kategori']}
💵 {nominal}
📅 {tx['tanggal']}

✅ Tersimpan ke Google Sheets"""
    send_message(chat_id, msg)

# ─── WEBHOOK HANDLER ──────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"ok": True})
    
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    
    if not text:
        return jsonify({"ok": True})
    
    # Commands
    if text == "/start":
        name = msg["from"].get("first_name", "Kamu")
        send_message(chat_id, f"Halo {name}! 👋\n\n{HELP_TEXT}")
        return jsonify({"ok": True})
    
    if text in ["/help", "/bantuan"]:
        send_message(chat_id, HELP_TEXT)
        return jsonify({"ok": True})
    
    if text in ["/saldo", "/ringkasan", "/summary"]:
        summary = get_summary_from_sheets(chat_id)
        send_message(chat_id, summary)
        return jsonify({"ok": True})
    
    # Parse transaction
    tx = parse_transaction(text)
    if tx:
        saved = save_to_sheets(tx)
        if saved:
            send_success(chat_id, tx)
        else:
            send_message(chat_id, "❌ Gagal menyimpan. Periksa koneksi Google Sheets.")
    else:
        send_message(chat_id, 
            "❓ Format tidak dikenali.\n\n"
            "Coba: `makan 25000` atau `gaji 5000000`\n"
            "Ketik /help untuk panduan lengkap."
        )
    
    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Finance Bot aktif ✅"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
