import requests
import time
import json
import os
from datetime import datetime, timedelta

# === VARIABLES DE ENTORNO ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Uno o varios IDs/Refs de pedido, separados por coma o en JSON array
LOGINEXT_ORDERS = os.getenv("LOGINEXT_ORDERS", "")

LOGINEXT_URL_DETAILS = os.getenv(
    "LOGINEXT_URL_DETAILS",
    "https://products.loginextsolutions.com/ShipmentApp/middlemile/shipment/order/iframe/details"
)

# Cabecera de autenticación, puedes sobrescribirla en Koyeb
DEFAULT_AUTH = "BASIC c586fa65-473e-454d-826b-448cea88b320"
LOGINEXT_AUTH = os.getenv("LOGINEXT_AUTH", DEFAULT_AUTH)

STATE_FILE = os.getenv("STATE_FILE", "estado.json")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "180"))

HEADERS = {
    "www-authenticate": LOGINEXT_AUTH,
    "Content-Type": "application/json"
}

# === Utilidades ===
def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Falta TELEGRAM_TOKEN o CHAT_ID.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
        if not r.ok:
            print("Error Telegram:", r.status_code, r.text)
    except Exception as e:
        print("Excepción Telegram:", e)

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def fmt_ts_local(ts_ms: int):
    dt_utc = datetime.utcfromtimestamp(ts_ms / 1000)
    dt_local = dt_utc - timedelta(hours=6)  # Honduras UTC-6
    return dt_local.strftime("%Y-%m-%d %H:%M:%S")

def parse_orders_env():
    s = LOGINEXT_ORDERS.strip()
    if not s:
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if x]
    except Exception:
        pass
    return [x.strip() for x in s.split(",") if x.strip()]

def fetch_details(order_id_or_ref: str):
    candidates = [
        {"orderRefId": order_id_or_ref},
        {"orderNo": order_id_or_ref},
    ]
    if order_id_or_ref.isdigit():
        candidates.append({"orderId": int(order_id_or_ref)})

    for payload in candidates:
        try:
            r = requests.post(LOGINEXT_URL_DETAILS,
                              headers=HEADERS,
                              json=payload,
                              timeout=25)
            if r.ok:
                j = r.json()
                if isinstance(j, dict) and "data" in j and j["data"]:
                    return j
        except Exception as e:
            print(f"Error con payload {payload}: {e}")
    return None

def extract_latest_event(resp: dict):
    """Devuelve {ts, event, node, raw} del evento más reciente."""
    if not resp or "data" not in resp:
        return None
    timeline = resp["data"].get("timeline", {})
    events = []
    for key, val in timeline.items():
        if not isinstance(val, dict):
            continue
        if key == "branch_to_branch":
            for node in val.get("subNodes", []):
                if "eventDt" in node:
                    events.append((
                        int(node["eventDt"]),
                        node.get("trackingEvent"),
                        node.get("nodeName", ""),
                        node
                    ))
        else:
            if "eventDt" in val:
                events.append((
                    int(val["eventDt"]),
                    val.get("trackingEvent"),
                    val.get("nodeName", ""),
                    val
                ))
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    ts, ev, node, raw = events[-1]
    return {"ts": ts, "event": ev, "node": node, "raw": raw}

def tracking_loop():
    print(f"✅ Bot activo, enviando a chat {CHAT_ID}")
    while True:
        state = load_state()
        orders = parse_orders_env()

        for order in orders:
            try:
                print(f"→ Consultando Loginext: {order}")
                resp = fetch_details(order)
                if not resp:
                    print("  No se obtuvo detalle.")
                    continue
                latest = extract_latest_event(resp)
                if not latest:
                    print("  Sin eventos en timeline.")
                    continue

                key = f"loginext::{order}"
                last_ts = int(state.get(key, 0))
                if latest["ts"] > last_ts:
                    order_no = resp["data"].get("orderNo", order)
                    order_status = resp["data"].get("orderStatus", "")
                    msg = (
                        f"🚚 Loginext\n"
                        f"Orden: {order_no}\n"
                        f"Evento: {latest['event']}\n"
                        f"Nodo: {latest['node']}\n"
                        f"Estado pedido: {order_status}\n"
                        f"Fecha (Tegucigalpa): {fmt_ts_local(latest['ts'])}"
                    )
                    print("  -> Nuevo evento, enviando Telegram.")
                    send_telegram(msg)
                    state[key] = latest["ts"]
                else:
                    print("  Sin cambios.")
            except Exception as e:
                print("  Error procesando orden:", order, e)

        save_state(state)
        print(f"--- Esperando {POLL_INTERVAL} segundos ---")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    tracking_loop()
