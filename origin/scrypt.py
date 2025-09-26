#!/usr/bin/env python3
# bot.py — multi-account trader with per-account proxies + randomness
# Исправлено: ошибки выводятся красным в консоли, точность из exchangeInfo

import os
import time
import json
import random
import hmac
import hashlib
import requests
import logging
from random import sample, shuffle
from time import sleep
from urllib.parse import urlencode
from typing import List, Dict, Optional, Tuple
from decimal import Decimal, getcontext, ROUND_DOWN

# Настройка логирования в файл
logging.basicConfig(filename='trading_bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

getcontext().prec = 28

# Цветной вывод для ошибок (красный)
def print_error(message: str) -> None:
    RED = "\033[91m"
    RESET = "\033[0m"
    print(f"{RED}{message}{RESET}")
    logging.error(message)

# =========================
# КЛЮЧЕВЫЕ НАСТРОЙКИ
# =========================
BASE_URL = os.getenv("ASTER_BASE", "https://fapi.asterdex.com")
KEYS_FILE = "keys.json"     # [{"api_key":"...","api_secret":"..."}] — порядок = порядку прокси
PROXY_FILE = "proxies.txt"  # host:port:user:pass на каждой строке
SYMBOL = "ASTERUSDT"

# Общая сумма позиции (база) и её разброс по циклам (±10%)
BASE_TOTAL_QTY = Decimal("300")
TOTAL_QTY_JITTER = Decimal("0.10")


# Время удержания позиции — случайно на каждый цикл
HOLD_TIME_RANGE: Tuple[int, int] = (30, 180)       # сек

# Пауза между циклами — случайно на каждый цикл
BETWEEN_CYCLES_RANGE: Tuple[int, int] = (5, 10)    # сек

# Коридоры долей (без нормализации к 100%)
LEG_SHARE_RANGES = [
    {"side": "SELL", "min": Decimal("0.50"), "max": Decimal("0.51")},
    {"side": "BUY",  "min": Decimal("0.30"), "max": Decimal("0.31")},
    {"side": "BUY",  "min": Decimal("0.18"), "max": Decimal("0.18")},
]
TOTAL_SHARE_SUM_RANGE: Tuple[Decimal, Decimal] = (Decimal("0.98"), Decimal("1.0"))

# Прокси и сеть
MIN_KEYS_REQUIRED = 3
REQUEST_TIMEOUT = 10.0
ORDER_FILL_POLL_INTERVAL = 0.5
ORDER_FILL_POLL_TIMEOUT = 10

# Оверрайд шагов лота (опционально, для тестов)
FORCE_LOT_STEP = Decimal("0.001")
FORCE_MIN_QTY  = Decimal("0.001")
USE_FORCE = False  # Отключено: используем значения из exchangeInfo

# Глобальные переменные для шага и минимального количества
LOT_STEP: Decimal = Decimal("0.001")
MIN_QTY:  Decimal = Decimal("0.001")

# =========================
# Загрузка ключей и прокси
# =========================
def load_keys_and_proxies() -> List[Dict[str, str]]:
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            keys = json.load(f)
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip()]

        if len(keys) != len(proxies):
            raise ValueError(f"Keys count ({len(keys)}) != proxies count ({len(proxies)})")

        accounts = []
        for i, k in enumerate(keys):
            if "api_key" not in k or "api_secret" not in k:
                raise ValueError(f"Key entry #{i} missing api_key/api_secret")
            host, port, user, pwd = proxies[i].split(":")
            proxy_url = f"http://{user}:{pwd}@{host}:{port}"
            accounts.append({
                "api_key": k["api_key"],
                "api_secret": k["api_secret"],
                "proxy": {"http": proxy_url, "https": proxy_url}
            })
        return accounts
    except Exception as e:
        print_error(f"Failed to load keys/proxies: {e}")
        raise

# =========================
# HTTP helpers
# =========================
def now_ms() -> int:
    return int(time.time() * 1000)

def sign(params: dict, secret: str) -> str:
    query = urlencode(params, doseq=True)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

def raise_with_body(r: requests.Response, path: str):
    try:
        msg = r.json()
    except Exception:
        msg = r.text
    raise RuntimeError(f"HTTP {r.status_code} {r.request.method} {path}: {msg}")

def public_get(path: str, params: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            raise_with_body(r, path)
        return r.json()
    except Exception as e:
        print_error(f"Public GET {path} failed: {e}")
        raise

def private_post(path: str, account: Dict[str, str], params: dict) -> dict:
    params = dict(params)
    params.setdefault("recvWindow", 5000)
    params.setdefault("timestamp", now_ms())
    params["signature"] = sign(params, account["api_secret"])
    headers = {"X-MBX-APIKEY": account["api_key"], "Content-Type": "application/x-www-form-urlencoded"}
    url = f"{BASE_URL}{path}"
    try:
        r = requests.post(url, headers=headers, data=params, timeout=REQUEST_TIMEOUT, proxies=account["proxy"])
        if not r.ok:
            raise_with_body(r, path)
        return r.json()
    except Exception as e:
        print_error(f"Private POST {path} failed: {e}")
        raise

def private_get(path: str, account: Dict[str, str], params: dict = None) -> dict:
    params = dict(params or {})
    params.setdefault("timestamp", now_ms())
    params.setdefault("recvWindow", 5000)
    params["signature"] = sign(params, account["api_secret"])
    headers = {"X-MBX-APIKEY": account["api_key"]}
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT, proxies=account["proxy"])
        if not r.ok:
            raise_with_body(r, path)
        return r.json()
    except Exception as e:
        print_error(f"Private GET {path} failed: {e}")
        raise

# =========================
# Ордерные helpers
# =========================
def set_leverage(account: Dict[str, str], symbol: str, leverage: int = 50) -> bool:
    """Устанавливает плечо для аккаунта и символа."""
    params = {
        "symbol": symbol,
        "leverage": str(leverage),
        "recvWindow": 5000,
        "timestamp": now_ms()
    }
    params["signature"] = sign(params, account["api_secret"])
    headers = {"X-MBX-APIKEY": account["api_key"], "Content-Type": "application/x-www-form-urlencoded"}
    url = f"{BASE_URL}/fapi/v1/leverage"
    try:
        r = requests.post(url, headers=headers, data=params, timeout=REQUEST_TIMEOUT, proxies=account["proxy"])
        if r.ok:
            logging.info(f"Set leverage {leverage}x for {symbol} via {account['proxy']['http'].split('@')[-1]}")
            return True
        else:
            raise_with_body(r, "/fapi/v1/leverage")
    except Exception as e:
        print_error(f"Failed to set leverage for {symbol}: {e}")
        return False


def place_market_order(account: Dict[str, str], side: str, quantity: Decimal, reduce_only: bool = False) -> dict:
    adj_qty = adjust_qty(quantity)
    if adj_qty < MIN_QTY:
        raise ValueError(f"Adjusted qty {adj_qty} < MIN_QTY {MIN_QTY}")
    params = {"symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": format_float(adj_qty)}
    if reduce_only:
        params["reduceOnly"] = "true"
    return private_post("/fapi/v1/order", account, params)


def get_order_status(account: Dict[str, str], order_id: int = None, client_oid: str = None) -> dict:
    params = {"symbol": SYMBOL}
    if order_id is not None:
        params["orderId"] = order_id
    if client_oid is not None:
        params["origClientOrderId"] = client_oid
    return private_get("/fapi/v1/order", account, params)

def wait_for_fill(account: Dict[str, str], order_id: int = None, client_oid: str = None,
                  timeout_s: float = ORDER_FILL_POLL_TIMEOUT) -> dict:
    start = time.time()
    last = {}
    while time.time() - start < timeout_s:
        try:
            last = get_order_status(account, order_id, client_oid)
            if last.get("status", "").upper() == "FILLED":
                return last
        except Exception as e:
            print_error(f"[wait_for_fill] warning: {e}")
        time.sleep(ORDER_FILL_POLL_INTERVAL)
    return last

# =========================
# exchangeInfo и квантование
# =========================
def load_symbol_filters():
    """Читает минимальные stepSize/minQty из LOT_SIZE и MARKET_LOT_SIZE."""
    global LOT_STEP, MIN_QTY
    try:
        info = public_get("/fapi/v1/exchangeInfo", params={"symbol": SYMBOL})
        s = info.get("symbols", [{}])[0]
        filters = s.get("filters", [])
        step_candidates = []
        min_candidates = []
        for f in filters:
            t = f.get("filterType")
            if t in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                if "stepSize" in f:
                    step_candidates.append(Decimal(str(f["stepSize"])))
                if "minQty" in f:
                    min_candidates.append(Decimal(str(f["minQty"])))
        LOT_STEP = min(step_candidates) if step_candidates else Decimal("0.001")
        MIN_QTY = min(min_candidates) if min_candidates else Decimal("0.001")
        print(f"Loaded filters for {SYMBOL}: stepSize={LOT_STEP}, minQty={MIN_QTY}")
        if USE_FORCE:
            LOT_STEP = FORCE_LOT_STEP
            MIN_QTY = FORCE_MIN_QTY
            print(f"Applied force override: stepSize={LOT_STEP}, minQty={MIN_QTY}")
    except Exception as e:
        print_error(f"Warning: failed to read exchangeInfo: {e}")
        LOT_STEP = Decimal("0.001")
        MIN_QTY = Decimal("0.001")

def floor_to_step(q: Decimal, step: Decimal) -> Decimal:
    steps = (q / step).to_integral_value(rounding=ROUND_DOWN)
    return steps * step

def adjust_qty(q: Decimal) -> Decimal:
    if q <= 0:
        return Decimal("0")
    adj = floor_to_step(q, LOT_STEP)
    if adj < MIN_QTY and q > 0:
        adj = MIN_QTY
    # Ограничиваем точность до шага биржи
    precision = abs(LOT_STEP.as_tuple().exponent)
    return adj.quantize(Decimal(f'0.{"0" * precision}'), rounding=ROUND_DOWN)

def format_float(x: Decimal) -> str:
    precision = abs(LOT_STEP.as_tuple().exponent)
    s = format(x.quantize(Decimal(f'0.{"0" * precision}'), rounding=ROUND_DOWN), 'f')
    return s.rstrip('0').rstrip('.') if '.' in s else s

# =========================
# Рандом параметров цикла
# =========================
def choose_total_qty() -> Decimal:
    factor = Decimal(str(random.uniform(float(1 - TOTAL_QTY_JITTER), float(1 + TOTAL_QTY_JITTER))))
    return BASE_TOTAL_QTY * factor


def sample_legs_with_sum_range() -> List[Dict[str, Decimal]]:
    low, high = TOTAL_SHARE_SUM_RANGE
    for _ in range(5000):
        s1 = Decimal(str(random.uniform(float(LEG_SHARE_RANGES[0]["min"]), float(LEG_SHARE_RANGES[0]["max"]))))
        s2 = Decimal(str(random.uniform(float(LEG_SHARE_RANGES[1]["min"]), float(LEG_SHARE_RANGES[1]["max"]))))
        s3 = Decimal(str(random.uniform(float(LEG_SHARE_RANGES[2]["min"]), float(LEG_SHARE_RANGES[2]["max"]))))
        total = s1 + s2 + s3
        if low <= total <= high:
            return [
                {"side": LEG_SHARE_RANGES[0]["side"], "share": s1},
                {"side": LEG_SHARE_RANGES[1]["side"], "share": s2},
                {"side": LEG_SHARE_RANGES[2]["side"], "share": s3},
            ]
    # Fallback: середины диапазонов
    return [
        {"side": LEG_SHARE_RANGES[0]["side"], "share": (LEG_SHARE_RANGES[0]["min"] + LEG_SHARE_RANGES[0]["max"]) / 2},
        {"side": LEG_SHARE_RANGES[1]["side"], "share": (LEG_SHARE_RANGES[1]["min"] + LEG_SHARE_RANGES[1]["max"]) / 2},
        {"side": LEG_SHARE_RANGES[2]["side"], "share": (LEG_SHARE_RANGES[2]["min"] + LEG_SHARE_RANGES[2]["max"]) / 2},
    ]

def random_hold_time() -> int:
    mn, mx = HOLD_TIME_RANGE
    return random.randint(int(mn), int(mx))

def random_between_pause() -> int:
    mn, mx = BETWEEN_CYCLES_RANGE
    return random.randint(int(mn), int(mx))

# =========================
# Один цикл торговли
# =========================
def run_cycle(accounts: List[Dict[str, str]], leverage: int = 50, max_retries: int = 3) -> None:
    """Выполняет один цикл торговли: открывает позиции (1 SELL, 2 BUY), удерживает и закрывает."""
    # Выбор и перемешивание 3 аккаунтов
    chosen = sample(accounts, min(3, len(accounts)))
    shuffle(chosen)

    # Рандомизация параметров
    total_qty = choose_total_qty()
    legs = sample_legs_with_sum_range()
    hold_time = random_hold_time()

    # Логирование начала цикла
    roles_text = ", ".join([f"{int(round(float(leg['share']) * 100))}% {leg['side']}" for leg in legs])
    print(f"\n=== New cycle @ {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Base qty: {format_float(total_qty)} {SYMBOL} | Legs: {roles_text} | Hold: {hold_time}s")
    logging.info(f"New cycle: qty={format_float(total_qty)} {SYMBOL}, legs={roles_text}, hold={hold_time}s")

    # Открытие позиций
    open_positions = []
    for idx, (account, leg) in enumerate(zip(chosen, legs), start=1):
        raw_qty = total_qty * leg["share"]
        adj_qty = adjust_qty(raw_qty)
        side = leg["side"]
        proxy_host = account['proxy']['http'].split('@')[-1]

        # Установка плеча
        if not set_leverage(account, SYMBOL, leverage):
            print_error(f"Skipping order for account #{idx} due to leverage failure")
            continue

        print(f"[OPEN] #{idx} via {proxy_host} {side} {format_float(raw_qty)} -> adj {format_float(adj_qty)} {SYMBOL}")
        logging.info(f"[OPEN] #{idx} via {proxy_host} {side} {format_float(raw_qty)} -> adj {format_float(adj_qty)} {SYMBOL}")

        # Попытки размещения ордера
        for attempt in range(max_retries):
            try:
                resp = place_market_order(account, side, adj_qty)
                order_id = resp.get("orderId")
                filled = wait_for_fill(account, order_id=order_id)
                status = filled.get('status', resp.get('status'))
                print(f"  -> Placed: orderId={order_id}, status={status}")
                logging.info(f"  -> Placed: orderId={order_id}, status={status}")
                open_positions.append({"account": account, "qty": adj_qty, "open_side": side})
                break
            except Exception as e:
                print_error(f"  ! Error placing open order (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    print_error(f"  ! Max retries reached for open order")
                sleep(1)

    # Ожидание удержания позиций
    if open_positions:
        print(f"Waiting {hold_time}s while positions are open...")
        logging.info(f"Waiting {hold_time}s while positions are open...")
        sleep(hold_time)

        # Закрытие позиций
        for info in open_positions:
            account = info["account"]
            qty = info["qty"]
            close_side = "SELL" if info["open_side"] == "BUY" else "BUY"
            proxy_host = account['proxy']['http'].split('@')[-1]
            print(f"[CLOSE] via {proxy_host} {close_side} {format_float(qty)} {SYMBOL} (reduceOnly)")
            logging.info(f"[CLOSE] via {proxy_host} {close_side} {format_float(qty)} {SYMBOL} (reduceOnly)")

            for attempt in range(max_retries):
                try:
                    resp = place_market_order(account, close_side, qty, reduce_only=True)
                    order_id = resp.get("orderId")
                    filled = wait_for_fill(account, order_id=order_id)
                    status = filled.get('status', resp.get('status'))
                    print(f"  -> Close: orderId={order_id}, status={status}")
                    logging.info(f"  -> Close: orderId={order_id}, status={status}")
                    break
                except Exception as e:
                    print_error(f"  ! Error placing close order (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        print_error(f"  ! Max retries reached for close order")
                    sleep(1)

    # Пауза перед следующим циклом
    pause = random_between_pause()
    print(f"Cycle finished. Waiting {pause}s before next cycle...")
    logging.info(f"Cycle finished. Waiting {pause}s before next cycle...")
    sleep(pause)

# =========================
# main
# =========================
def main():
    try:
        accounts = load_keys_and_proxies()
    except Exception as e:
        print_error(f"Failed to load keys/proxies: {e}")
        return

    if len(accounts) < MIN_KEYS_REQUIRED:
        print_error(f"Need at least {MIN_KEYS_REQUIRED} accounts. Currently: {len(accounts)}")
        return

    load_symbol_filters()
    print(f"Loaded {len(accounts)} accounts. Using step={LOT_STEP}, minQty={MIN_QTY}. Press Ctrl+C to stop.")
    logging.info(f"Loaded {len(accounts)} accounts. Using step={LOT_STEP}, minQty={MIN_QTY}")
    try:
        while True:
            run_cycle(accounts)
    except KeyboardInterrupt:
        print("Stopped.")
        logging.info("Bot stopped by user")
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logging.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()