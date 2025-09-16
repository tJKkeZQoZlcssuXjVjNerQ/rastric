#!/usr/bin/env python3
import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

# === VARIABLES DE ENTORNO ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Ordenes: puedes poner "409460981-1,409048718-1" o '["409460981-1","409048718-1"]'
LOGINEXT_ORDERS = os.getenv("LOGINEXT_ORDERS", "")

# URL donde siempre se hace la consulta
LOGINEXT_URL_DETAILS = os.getenv(
    "LOGINEXT_URL_DETAILS",
    "https://products.loginextsolutions.com/ShipmentApp/middlemile/shipment/order/iframe/details"
)

# Cabecera de autenticación (usa la tuya en Koyeb si la necesitas)
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
        print("❌ TELEGRAM_TOKEN o CHAT_ID no configurados.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
        if not r.ok:
            print("Error Telegram:", r.status_code, r.text)
    except Exception as e:
        print("Excepción al enviar Telegram:", e)

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
    try:
        dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        dt_local = dt_utc - timedelta(hours=6)  # Tegucigalpa UTC-6 (sin DST)
        return dt_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_ms)

def parse_orders_env():
    s = (LOGINEXT_ORDERS or "").strip()
    if not s:
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if x]
    except Exception:
        pass
    return [x.strip() for x in s.split(",") if x.strip()]

# === Función que siempre manda el payload solicitado ===
def fetch_details_for_order(order_no: str):
    """
    Envía exactamente: {"userType":"DELIVERCUSTOMER","orderNo": "<order_no>"}
    a LOGINEXT_URL_DETAILS con HEADERS.
    """
    payload = {"userType": "DELIVERCUSTOMER", "orderNo": order_no}
    try:
        r = requests.post(LOGINEXT_URL_DETAILS, headers=HEADERS, json=payload, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error consultando Loginext para {order_no}: {e}")
        return None

def extract_latest_event_from_response(resp: dict):
    """
    Recorre resp['data']['timeline'] (incluyendo branch_to_branch.subNodes)
    y devuelve el evento más reciente como: {ts, event, node, raw}
    """
    if not resp or "data" not in resp:
        return None
    timeline = resp["data"].get("timeline", {}) or {}
    events = []
    for key, val in timeline.items():
        if not isinstance(val, dict):
            continue
        if key == "branch_to_branch":
            for node in val.get("subNodes", []):
                if "eventDt" in node:
                    try:
                        events.append((int(node["eventDt"]), node.get("trackingEvent"), node.get("nodeName", ""), node))
                    except Exception:
                        pass
        else:
            if "eventDt" in val:
                try:
                    events.append((int(val["eventDt"]), val.get("trackingEvent"), val.get("nodeName", ""), val))
                except Exception:
                    pass
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    ts, ev, node, raw = events[-1]
    return {"ts": ts, "event": ev, "node": node, "raw": raw}

# === Loop principal ===
def tracking_loop():
    print(f"✅ Servicio Loginext iniciado. Enviando a chat {CHAT_ID}")
    while True:
        state = load_state()
        orders = parse_orders_env()

        if not orders:
            print("⚠️ LOGINEXT_ORDERS no configurado. Setea la variable de entorno con orderNo(s).")
        for order in orders:
            try:
                print(f"→ Consultando Loginext para orderNo: {order}")
                resp = fetch_details_for_order(order)
                if not resp:
                    print("  No se obtuvo respuesta válida.")
                    continue

                latest = extract_latest_event_from_response(resp)
                if not latest:
                    print("  No hay eventos en timeline.")
                    continue

                key = f"loginext::{order}"
                last_ts = int(state.get(key, 0))

                if latest["ts"] > last_ts:
                    order_no = resp.get("data", {}).get("orderNo", order)
                    order_status = resp.get("data", {}).get("orderStatus", "")
                    fecha_local = fmt_ts_local(latest["ts"])
                    event_name = latest.get("event") or "EVENT"
                    node_name = latest.get("node") or latest["raw"].get("nodeType", "")
                    # Si el evento trae epod/esign, incluimos primera url (opcional)
                    epod_url = None
                    raw = latest.get("raw", {})
                    if isinstance(raw, dict):
                        if raw.get("epodList"):
                            try:
                                epod_url = raw["epodList"][0].get("url")
                            except Exception:
                                epod_url = None
                        elif raw.get("esignList"):
                            try:
                                epod_url = raw["esignList"][0].get("url")
                            except Exception:
                                epod_url = None

                    msg = (
                        f"🚚 Loginext\n"
                        f"Orden: {order_no}\n"
                        f"Evento: {event_name}\n"
                        f"Nodo: {node_name}\n"
                        f"Estado pedido: {order_status}\n"
                        f"Fecha (Tegucigalpa): {fecha_local}"
                    )
                    if epod_url:
                        msg += f"\nEPOD/ESIGN: {epod_url}"

                    print("  -> Nuevo evento detectado. Enviando Telegram.")
                    send_telegram(msg)
                    state[key] = int(latest["ts"])
                else:
                    print(f"  Sin cambios para {order}. (último guardado: {last_ts})")
            except Exception as e:
                print("  Error procesando orden", order, e)

        save_state(state)
        print(f"--- Esperando {POLL_INTERVAL} segundos ---\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    tracking_loop()
