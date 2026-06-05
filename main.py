# btc_dashboard_v8_3_final.py
import requests
import time
import math
import sys
import csv
import os
import collections
from datetime import datetime, UTC

VERSION = "BTC Dashboard v8.3 (Structure vs Expansion Mod)"
print(f"🔄 Framework initialized using {VERSION}.")
print("🔄 Fetching live data matrices across global exchanges...")

# ═══════════════════════════════════════════════
# SECTION 1 — UPGRADED DUAL DATA FETCH
# ═══════════════════════════════════════════════

def fetch_gateio_native():
    try:
        # 1. Pull Derivatives Stats (Open Interest & Taker Volume)
        stats_url = "https://api.gateio.ws/api/v4/futures/usdt/contract_stats"
        from_ts = int(time.time()) - (5 * 24 * 3600)
        stats_params = {"contract": "BTC_USDT", "from": from_ts, "interval": "1h", "limit": "120"}
        stats_raw = requests.get(stats_url, params=stats_params, timeout=10).json()
        
        if not isinstance(stats_raw, list):
            raise ValueError("Invalid response format from Gate.io Stats")
        stats_raw.sort(key=lambda x: float(x.get('time', 0)))
        
        # 2. Pull Price Structure (True High and Low Prices)
        kline_url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
        kline_params = {"contract": "BTC_USDT", "from": from_ts, "interval": "1h", "limit": "120"}
        kline_raw = requests.get(kline_url, params=kline_params, timeout=10).json()
        
        if not isinstance(kline_raw, list):
            raise ValueError("Invalid response format from Gate.io Candlesticks")
        kline_raw.sort(key=lambda x: float(x.get('t', 0)))
        
        # 3. Create a Fast Lookup Map for Price Structure using Timestamps
        kline_map = {}
        for k in kline_raw:
            ts = int(float(k.get('t', 0)))
            kline_map[ts] = {
                'high': float(k.get('h', 0.0)),
                'low': float(k.get('l', 0.0)),
                'close': float(k.get('c', 0.0))
            }
            
        # 4. Merge Datasets via Timestamp Matching
        data = []
        running_cvd = 0.0
        for x in stats_raw:
            ts = int(float(x.get('time', 0)))
            
            k_data = kline_map.get(ts, None)
            if not k_data:
                continue 
                
            buy_vol = float(x.get('long_taker_size', 0.0))
            sell_vol = float(x.get('short_taker_size', 0.0))
            delta = buy_vol - sell_vol
            running_cvd += delta
            
            oi_usd = float(x.get('open_interest_usd', 0.0))
            
            data.append({
                'time': float(ts),
                'price': k_data['close'],
                'high': k_data['high'],
                'low': k_data['low'],
                'OI_USD': oi_usd / 1e9,
                'lsr_taker': float(x.get('lsr_taker', 1.0)),
                'lsr_account': float(x.get('lsr_account', 1.0)),
                'top_lsr': float(x.get('top_lsr_size', 1.0)),
                'long_liq': float(x.get('long_liq_usd', 0.0)),
                'short_liq': float(x.get('short_liq_usd', 0.0)),
                'buy_vol': buy_vol,
                'sell_vol': sell_vol,
                'delta': delta,
                'cvd': running_cvd
            })
            
        fr_raw = requests.get("https://api.gateio.ws/api/v4/futures/usdt/funding_rate",
                              params={"contract": "BTC_USDT", "limit": "120"}, timeout=10).json()
        fr_data = []
        if isinstance(fr_raw, list):
            fr_raw.sort(key=lambda x: float(x.get('t', 0)))
            fr_data = [{'time': float(x.get('t', 0)), 'rate': float(x.get('r', 0.0)) * 100} for x in fr_raw]
        
        return data, fr_data
    except Exception as e:
        print(f"❌ Gate.io Fetch Error: {e}")
        return [], []

def fetch_binance_futures_native():
    B = "https://fapi.binance.com"
    H = {"User-Agent": "Mozilla/5.0"}
    P = {"symbol": "BTCUSDT", "period": "1h", "limit": "120"}
    
    def get_api(path, params=P):
        resp = requests.get(f"{B}{path}", params=params, headers=H, timeout=10).json()
        if isinstance(resp, dict) and 'msg' in resp: raise ValueError(resp['msg'])
        if not resp: raise ValueError("Empty response")
        return resp

    oi_raw = get_api("/futures/data/openInterestHist")
    oi_raw.sort(key=lambda x: float(x.get('timestamp', 0)))
    
    top_raw = get_api("/futures/data/topLongShortAccountRatio")
    top_raw.sort(key=lambda x: float(x.get('timestamp', 0)))
    
    pos_raw = get_api("/futures/data/topLongShortPositionRatio")
    pos_raw.sort(key=lambda x: float(x.get('timestamp', 0)))
    
    glob_raw = get_api("/futures/data/globalLongShortAccountRatio")
    glob_raw.sort(key=lambda x: float(x.get('timestamp', 0)))
    
    fr_raw = get_api("/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": "100"})
    fr_raw.sort(key=lambda x: float(x.get('fundingTime', 0)))
    
    return oi_raw, top_raw, pos_raw, glob_raw, fr_raw

def fetch_binance_spot_native():
    resp = requests.get("https://api.binance.com/api/v3/klines",
                        params={"symbol": "BTCUSDT", "interval": "1h", "limit": "48"},
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
    if isinstance(resp, dict) and 'msg' in resp: raise ValueError(resp['msg'])
    
    spot_data = []
    running_spot_cvd = 0.0
    for k in resp:
        vol = float(k[5])
        taker_buy = float(k[9])
        taker_sell = vol - taker_buy
        delta = taker_buy - taker_sell
        running_spot_cvd += delta
        
        spot_data.append({
            'time': float(k[0]) / 1000,
            'close': float(k[4]),
            'spot_vol': vol,
            'taker_buy': taker_buy,
            'taker_sell': taker_sell,
            'spot_delta': delta,
            'spot_cvd': running_spot_cvd
        })
    return spot_data

# ═══════════════════════════════════════════════
# SECTION 2 — CORE PROCESSING PIPELINES
# ═══════════════════════════════════════════════

gate_df, gate_fr = fetch_gateio_native()
binance_available = spot_available = False

if len(gate_df) == 0:
    print("❌ Fatal Exception: Core market matrix down.")
    sys.exit()

try:
    bn_oi, bn_top, bn_pos, bn_glob, bn_fr = fetch_binance_futures_native()
    binance_available = True
except Exception as e:
    print(f"❌ Binance Futures Error: {e}")

try:
    spot_df = fetch_binance_spot_native()
    spot_available = True
except Exception as e:
    print(f"❌ Binance Spot Error: {e}")

data_quality = "GOOD"
if not binance_available and not spot_available:
    data_quality = "PARTIAL (Gate Only)"
elif not binance_available or not spot_available:
    data_quality = "PARTIAL"

# ═══════════════════════════════════════════════
# SECTION 3 — BACKGROUND LOGIC
# ═══════════════════════════════════════════════

latest = gate_df[-1]
len_12 = min(12, len(gate_df))
price_change = latest['price'] - gate_df[-len_12]['price'] if len_12 > 0 else 0
gate_fr_latest = gate_fr[-1]['rate'] if len(gate_fr) > 0 else 0

if binance_available and len(bn_top) > 0 and len(bn_fr) > 0:
    bn_latest_top = float(bn_top[-1]['longShortRatio'])
    bn_fr_latest = float(bn_fr[-1]['fundingRate']) * 100
    smart_gap = abs(bn_latest_top - latest['top_lsr'])
    agg_smart_lsr = 1.0 if smart_gap > 1.0 else (bn_latest_top * 0.65) + (latest['top_lsr'] * 0.35)
    agg_fr = (bn_fr_latest * 0.65) + (gate_fr_latest * 0.35)
    exchange_agreement = ((bn_latest_top > 1 and latest['top_lsr'] > 1) or (bn_latest_top < 1 and latest['top_lsr'] < 1)) and smart_gap <= 0.50
else:
    bn_latest_top = 1.0
    agg_smart_lsr = latest['top_lsr']
    smart_gap = 0
    agg_fr = gate_fr_latest
    exchange_agreement = True

# ═══════════════════════════════════════════════
# SECTION 4 — MODEL 1 COMPONENTS
# ═══════════════════════════════════════════════

len_24 = min(24, len(gate_df))
len_72 = min(72, len(gate_df))
ma24 = sum([x['price'] for x in gate_df[-len_24:]]) / len_24 if len_24 > 0 else latest['price']
ma72 = sum([x['price'] for x in gate_df[-len_72:]]) / len_72 if len_72 > 0 else latest['price']

if ma24 > ma72:
    if latest['price'] > ma24: c1_label, c1_score = "STRONG BULL", 25
    else: c1_label, c1_score = "BULL", 15
elif ma24 < ma72:
    if latest['price'] < ma24: c1_label, c1_score = "STRONG BEAR", -25
    else: c1_label, c1_score = "BEAR", -15
else:
    c1_label, c1_score = "NEUTRAL", 0

deltas_6h = [sum([x['delta'] for x in gate_df[max(0, i-5):i+1]]) for i in range(len(gate_df))]
tail_len = min(48, len(deltas_6h))
tail_deltas = deltas_6h[-tail_len:]
cvd_6h_mean = sum(tail_deltas) / tail_len if tail_len > 0 else 0
cvd_6h_std = math.sqrt(sum((x - cvd_6h_mean) ** 2 for x in tail_deltas) / tail_len) if tail_len > 0 else 1
cvd_z = (deltas_6h[-1] - cvd_6h_mean) / cvd_6h_std if cvd_6h_std > 0 else 0

if cvd_z > 1.0: c2_label, c2_score = "AGGRESSIVE BUYING", 25
elif cvd_z > 0.3: c2_label, c2_score = "BUYING", 15
elif cvd_z < -1.0: c2_label, c2_score = "AGGRESSIVE SELLING", -25
elif cvd_z < -0.3: c2_label, c2_score = "SELLING", -15
else: c2_label, c2_score = "NEUTRAL", 0

oi_changes = [gate_df[i]['OI_USD'] - gate_df[i-1]['OI_USD'] for i in range(1, len(gate_df))] or [0]
oi_tail_len = min(48, len(oi_changes))
tail_oi = oi_changes[-oi_tail_len:]
oi_mean = sum(tail_oi) / oi_tail_len if oi_tail_len > 0 else 0
oi_std = math.sqrt(sum((x - oi_mean) ** 2 for x in tail_oi) / oi_tail_len) if oi_tail_len > 0 else 1
oi_z = (oi_changes[-1] - oi_mean) / oi_std if oi_std > 0 else 0

if oi_z > 0.8:
    if price_change > 0: c3_label, c3_score = "LONG BUILDUP", 20
    else: c3_label, c3_score = "SHORT BUILDUP", -20
elif oi_z < -0.8:
    if price_change < 0: c3_label, c3_score = "LONG FLUSH", -10
    else: c3_label, c3_score = "SHORT FLUSH", 10
else:
    c3_label, c3_score = "NEUTRAL", 0

if spot_available and len(spot_df) > 0:
    spot_buying = spot_df[-1]['taker_buy'] > spot_df[-1]['taker_sell']
    spot_cvd_rising = spot_df[-1]['spot_cvd'] > spot_df[-min(12, len(spot_df))]['spot_cvd']
    if spot_buying and spot_cvd_rising: c4_label, c4_score = "BUYING", 15
    elif not spot_buying and not spot_cvd_rising: c4_label, c4_score = "SELLING", -15
    else: c4_label, c4_score = "NEUTRAL", 0
else:
    c4_label, c4_score = "NEUTRAL", 0

if agg_smart_lsr > 1.30: c5_label, c5_score = "STRONG SMART BUYING", 15
elif agg_smart_lsr > 1.10: c5_label, c5_score = "SMART BUYING", 8
elif agg_smart_lsr < 0.70: c5_label, c5_score = "STRONG SMART SELLING", -15
elif agg_smart_lsr < 0.90: c5_label, c5_score = "SMART SELLING", -8
else: c5_label, c5_score = "NEUTRAL", 0

# ═══════════════════════════════════════════════
# SECTION 5 — MODEL 1 AGGREGATION
# ═══════════════════════════════════════════════

total_score = c1_score + c2_score + c3_score + c4_score + c5_score
MAX_SCORE = 100
confidence = round(abs(total_score) / MAX_SCORE * 100)
confidence = min(confidence, 100)

if total_score >= 70: direction = "STRONG LONG"
elif total_score >= 40: direction = "LONG"
elif total_score > -40: direction = "NEUTRAL"
elif total_score > -70: direction = "SHORT"
else: direction = "STRONG SHORT"

direction_meanings = {
    "STRONG LONG": "Strong bullish control",
    "LONG": "Bullish advantage",
    "NEUTRAL": "Bulls and bears evenly matched",
    "SHORT": "Bearish advantage",
    "STRONG SHORT": "Strong bearish control"
}
direction_meaning = direction_meanings.get(direction, "Unknown condition")

if confidence >= 90: grade = "A+"
elif confidence >= 80: grade = "A"
elif confidence >= 70: grade = "B"
elif confidence >= 60: grade = "C"
else: grade = "D"

grade_desc = {
    "A+": "Extreme Conviction", "A": "High Conviction",
    "B": "Moderate Conviction", "C": "Weak Bias", "D": "No Clear Edge"
}.get(grade, "Unknown")

# ═══════════════════════════════════════════════
# SECTION 6 — MODEL 2 COMPONENTS
# ═══════════════════════════════════════════════

intra_hour_ranges = []
lookback_24h = gate_df[-min(24, len(gate_df)):]

for x in lookback_24h:
    h = x.get('high', x['price'])
    l = x.get('low', x['price'])
    intra_hour_ranges.append(h - l)

atr_usd = sum(intra_hour_ranges) / len(intra_hour_ranges) if intra_hour_ranges else 500.0

current_hour = gate_df[-1]
current_range = current_hour.get('high', current_hour['price']) - current_hour.get('low', current_hour['price'])

vm = current_range / atr_usd if atr_usd > 0 else 1.0

trend_gap_pct = (abs(ma24 - ma72) / ma72 * 100) if ma72 > 0 else 0
if trend_gap_pct > 2.0: m2_c1_score = 25
elif trend_gap_pct >= 1.0: m2_c1_score = 20
elif trend_gap_pct >= 0.5: m2_c1_score = 10
else: m2_c1_score = 0

abs_oi_z = abs(oi_z)
if abs_oi_z > 1.5: m2_c2_score = 25
elif abs_oi_z >= 1.0: m2_c2_score = 18
elif abs_oi_z >= 0.5: m2_c2_score = 10
else: m2_c2_score = 0

abs_cvd_z = abs(cvd_z)
if abs_cvd_z > 1.5: m2_c3_score = 20
elif abs_cvd_z >= 0.8: m2_c3_score = 15
elif abs_cvd_z >= 0.3: m2_c3_score = 8
else: m2_c3_score = 0

long_liq, short_liq = latest['long_liq'], latest['short_liq']
liq_ratio = max(long_liq, short_liq) / max(min(long_liq, short_liq), 1)
liq_ratio = min(liq_ratio, 20) 
if liq_ratio > 8: m2_c4_score = 15
elif liq_ratio >= 4: m2_c4_score = 10
elif liq_ratio >= 2: m2_c4_score = 5
else: m2_c4_score = 0

if vm >= 3.0:     m2_c5_score = 15
elif vm >= 2.0:   m2_c5_score = 12
elif vm >= 1.5:   m2_c5_score = 10
elif vm >= 1.0:   m2_c5_score = 7
elif vm >= 0.5:   m2_c5_score = 4
else:             m2_c5_score = 0

# ═══════════════════════════════════════════════
# SECTION 7 — MODEL 2 AGGREGATION
# ═══════════════════════════════════════════════

expansion_score = m2_c1_score + m2_c2_score + m2_c3_score + m2_c4_score + m2_c5_score

if expansion_score >= 81:
    exp_grade, exp_grade_desc = "A+", "Extreme Energy"
    classification = "EXPLOSIVE MOVE"
    lower_mult, upper_mult = 2.0, 3.0
elif expansion_score >= 61:
    exp_grade, exp_grade_desc = "A", "High Energy"
    classification = "STRONG EXPANSION"
    lower_mult, upper_mult = 1.5, 2.0
elif expansion_score >= 41:
    exp_grade, exp_grade_desc = "B", "Moderate Energy"
    classification = "TRADEABLE MOVE"
    lower_mult, upper_mult = 1.0, 1.5
elif expansion_score >= 21:
    exp_grade, exp_grade_desc = "C", "Low Energy"
    classification = "NORMAL MARKET"
    lower_mult, upper_mult = 0.5, 1.0
else:
    exp_grade, exp_grade_desc = "D", "Dead Energy"
    classification = "DEAD MARKET"
    lower_mult, upper_mult = 0.0, 0.5

class_interpretations = {
    "DEAD MARKET": "Avoid breakout trades",
    "NORMAL MARKET": "Small moves likely",
    "TRADEABLE MOVE": "Good environment for momentum trades",
    "STRONG EXPANSION": "Large move likely",
    "EXPLOSIVE MOVE": "Extreme volatility expected"
}
classification_interpretation = class_interpretations.get(classification, "")

expected_move_lower = atr_usd * lower_mult
expected_move_upper = atr_usd * upper_mult

# Retrieve Previous Expansion Score Memory-Efficiently
prev_exp_score = None
log_file = "btc_dashboard_log.csv"
if os.path.exists(log_file):
    try:
        with open(log_file, "r", newline="") as f:
            reader = csv.reader(f)
            headers_in_file = next(reader, None)
            if headers_in_file and "expansion_score" in headers_in_file:
                idx = headers_in_file.index("expansion_score")
                last_row = collections.deque(reader, maxlen=1)
                if last_row:
                    prev_exp_score = int(last_row[0][idx])
    except Exception:
        pass

if prev_exp_score is not None:
    diff = expansion_score - prev_exp_score
    if diff > 0: expansion_trend_str = f"RISING (+{diff})"
    elif diff < 0: expansion_trend_str = f"FALLING ({diff})"
    else: expansion_trend_str = "FLAT"
else:
    expansion_trend_str = "N/A (First Run)"

# ═══════════════════════════════════════════════
# SECTION 8 — MODEL 3 COMPONENTS (DECISION ENGINE)
# ═══════════════════════════════════════════════

# --- 8A: STRUCTURE ENGINE ---
stable_bull_trigger = max([x.get('high', x['price']) for x in lookback_24h])
stable_bear_trigger = min([x.get('low', x['price']) for x in lookback_24h])

# --- 8B: VOLATILE TRIGGER ENGINE ---
volatile_bull_trigger = latest['price'] + expected_move_lower
volatile_bear_trigger = latest['price'] - expected_move_lower

# --- 8C: TRIGGER GAP ANALYSIS ---
bull_gap = volatile_bull_trigger - stable_bull_trigger
bear_gap = stable_bear_trigger - volatile_bear_trigger

# Using a tight buffer ($25) to define '≈ 0'
GAP_BUFFER = 25 
if bull_gap > GAP_BUFFER: bull_gap_status = "Bullish Expansion Pressure"
elif bull_gap < -GAP_BUFFER: bull_gap_status = "Weak Expansion"
else: bull_gap_status = "Neutral"

if bear_gap > GAP_BUFFER: bear_gap_status = "Bearish Expansion Pressure"
elif bear_gap < -GAP_BUFFER: bear_gap_status = "Weak Expansion"
else: bear_gap_status = "Neutral"

# --- 8D: BREAKOUT POWER RATIO ---
distance_to_res = max(stable_bull_trigger - latest['price'], 1)
bull_power_ratio = expected_move_lower / distance_to_res

distance_to_sup = max(latest['price'] - stable_bear_trigger, 1)
bear_power_ratio = expected_move_lower / distance_to_sup

if "LONG" in direction: active_ratio = bull_power_ratio
elif "SHORT" in direction: active_ratio = bear_power_ratio
else: active_ratio = max(bull_power_ratio, bear_power_ratio)

if active_ratio >= 1.50: power_status, m3_c5 = "HIGH BREAKOUT PROBABILITY", 15
elif active_ratio >= 1.00: power_status, m3_c5 = "BREAKOUT POSSIBLE", 10
elif active_ratio >= 0.70: power_status, m3_c5 = "STRUCTURE TEST ONLY", 5
else: power_status, m3_c5 = "LOW BREAKOUT PROBABILITY", 0

if active_ratio >= 1.00:
    power_interpretation = "Expansion exceeds nearby structure.\n Energy exists for a breakout if directional confirmation appears."
elif active_ratio >= 0.70:
    power_interpretation = "Expansion approaches structure.\n Structure test likely, but breakout lacks high conviction energy."
else:
    power_interpretation = "Expansion falls short of structure.\n Insufficient energy for a structural breakout."

# --- DECISION ENGINE BASE SCORING ---
if direction in ["STRONG LONG", "STRONG SHORT"]: m3_c1 = 40
elif direction in ["LONG", "SHORT"]: m3_c1 = 25
else: m3_c1 = 0

if classification == "EXPLOSIVE MOVE": m3_c2 = 30
elif classification == "STRONG EXPANSION": m3_c2 = 25
elif classification == "TRADEABLE MOVE": m3_c2 = 15
elif classification == "NORMAL MARKET": m3_c2 = 5
else: m3_c2 = 0

if confidence >= 90: m3_c3 = 20
elif confidence >= 80: m3_c3 = 15
elif confidence >= 70: m3_c3 = 10
elif confidence >= 60: m3_c3 = 5
else: m3_c3 = 0

if data_quality == "GOOD": m3_c4 = 10
elif data_quality == "PARTIAL": m3_c4 = 5
else: m3_c4 = 0

# Max Score conceptually moves from 100 to 115 due to M3_C5 (Breakout Engine)
decision_score = m3_c1 + m3_c2 + m3_c3 + m3_c4 + m3_c5

exp_levels = {"DEAD MARKET": 1, "NORMAL MARKET": 2, "TRADEABLE MOVE": 3, "STRONG EXPANSION": 4, "EXPLOSIVE MOVE": 5}
current_exp_level = exp_levels.get(classification, 1)

if direction == "STRONG LONG" and current_exp_level >= 4 and confidence >= 80:
    setup_type = "AGGRESSIVE LONG"
elif direction in ["LONG", "STRONG LONG"] and current_exp_level >= 4:
    setup_type = "LONG"
elif direction == "STRONG SHORT" and current_exp_level >= 4 and confidence >= 80:
    setup_type = "AGGRESSIVE SHORT"
elif direction in ["SHORT", "STRONG SHORT"] and current_exp_level >= 4:
    setup_type = "SHORT"
elif direction in ["LONG", "SHORT"] and current_exp_level == 3:
    setup_type = "WATCHLIST"
elif direction == "NEUTRAL":
    if classification in ["STRONG EXPANSION", "EXPLOSIVE MOVE"]:
        setup_type = "BREAKOUT WATCH"
    elif classification == "TRADEABLE MOVE":
        setup_type = "WATCHLIST"
    else:
        setup_type = "NO TRADE"
else:
    setup_type = "NO TRADE"

setup_meanings = {
    "NO TRADE": "No statistical edge",
    "WATCHLIST": "Potential setup forming",
    "BREAKOUT WATCH": "Energy present, direction missing",
    "LONG": "Directional edge confirmed",
    "SHORT": "Directional edge confirmed",
    "AGGRESSIVE LONG": "High conviction bullish setup",
    "AGGRESSIVE SHORT": "High conviction bearish setup"
}
setup_meaning = setup_meanings.get(setup_type, "")

if "AGGRESSIVE" in setup_type:
    trade_status, confirmation_status, action = "ACTIVE", "PASSED", f"ENTER {setup_type.split()[-1]}"
elif setup_type in ["LONG", "SHORT"]:
    trade_status, confirmation_status, action = "ACTIVE", "PASSED", f"ENTER {setup_type}"
elif setup_type == "BREAKOUT WATCH":
    trade_status, confirmation_status = "STANDBY", "PENDING"
    action = f"WAIT FOR BREAKOUT | Potential Move: ${expected_move_lower:,.0f}-${expected_move_upper:,.0f}"
elif setup_type == "WATCHLIST":
    trade_status, confirmation_status = "STANDBY", "PENDING"
    action = "MONITOR FOR DIRECTIONAL EDGE"
else:
    trade_status, confirmation_status, action = "INACTIVE", "FAILED", "SIT ON HANDS"

# ═══════════════════════════════════════════════
# SECTION 9 — CONSOLIDATED TRADER DASHBOARD
# ═══════════════════════════════════════════════

C_GREEN = "\033[92m" if total_score >= 40 else ""
C_RED = "\033[91m" if total_score <= -40 else ""
C_YELLOW = "\033[93m" if -40 < total_score < 40 else ""
C_CYAN = "\033[96m"
C_MAGENTA = "\033[95m"
C_RESET = "\033[0m"

dir_color = C_GREEN if "LONG" in direction else (C_RED if "SHORT" in direction else C_YELLOW)
struct_icon = "---" 
if total_score >= 40: struct_icon = "UP"
elif total_score <= -40: struct_icon = "DOWN"

print("\n" + "═"*60)
print(f" {C_CYAN}BTC COMBINED DASHBOARD — {VERSION}{C_RESET}")
print("═"*60)

print(f" {C_CYAN}BTC PRICE    : ${latest['price']:,.0f}{C_RESET}")
print(f" DIRECTION    : {dir_color}[{struct_icon}] {direction}{C_RESET}")
print(f" MEANING      : {direction_meaning}")
print(f" CONFIDENCE   : {dir_color}{confidence}%{C_RESET}")
print(f" GRADE        : {grade} ({grade_desc})")
print("─"*60)

print(f" TREND        : {c1_label:<20} | Score: {abs(c1_score)}/25")
print(f" CVD          : {c2_label:<20} | Score: {abs(c2_score)}/25")
print(f" OPEN INTEREST: {c3_label:<20} | Score: {abs(c3_score)}/20")
print(f" SPOT         : {c4_label:<20} | Score: {abs(c4_score)}/15")
print(f" SMART MONEY  : {c5_label:<20} | Score: {abs(c5_score)}/15")
print("─"*60)
print(f" M1 SCORE     : {total_score}/100")

print("\n" + "═"*60)
print(f" {C_MAGENTA}MODEL 2: EXPANSION & ENERGY{C_RESET}")
print("═"*60)

print(f" 24H TRUE RANGE ATR       : ${atr_usd:,.0f}")
print(f" ACTIVE HOUR METRIC (Vm)  : {vm:.2f}x Baseline")
print(f" EXPECTED EXPANSION       : ${expected_move_lower:,.0f} - ${expected_move_upper:,.0f}")
print("─"*60)
print(f" CLASSIFICATION           : {classification}")
print(f" INTERPRETATION           : {classification_interpretation}")
print(f" EXPANSION SCORE          : {expansion_score}/100")
print(f" EXPANSION TREND          : {expansion_trend_str}")

print("\n" + "="*60)
print(f" {C_YELLOW}STRUCTURE vs EXPANSION ANALYSIS{C_RESET}")
print("="*60)
print(f" Stable Bull Trigger   : ${stable_bull_trigger:,.0f}")
print(f" Stable Bear Trigger   : ${stable_bear_trigger:,.0f}")
print(f" Volatile Bull Trigger : ${volatile_bull_trigger:,.0f}")
print(f" Volatile Bear Trigger : ${volatile_bear_trigger:,.0f}")
print("─"*60)
print(f" Bull Gap              : {'+' if bull_gap > 0 else ''}{bull_gap:,.0f} ({bull_gap_status})")
print(f" Bear Gap              : {'+' if bear_gap > 0 else ''}{bear_gap:,.0f} ({bear_gap_status})")
print(f" Bull Power Ratio      : {bull_power_ratio:.2f}")
print(f" Bear Power Ratio      : {bear_power_ratio:.2f}")
print("─"*60)
print(" Interpretation:")
print(f" {power_interpretation}")

print("\n" + "="*60)
print(f" {C_YELLOW}MODEL 3 — DECISION ENGINE{C_RESET}")
print("="*60)
print(f" DECISION SCORE : {decision_score}/115 (Analytics Only)")
print(f" SETUP TYPE     : {setup_type}")
print(f" MEANING        : {setup_meaning}")
print(f" TRADE STATUS   : {trade_status}")
print(f" CONFIRMATION   : {confirmation_status}")
print(f" ACTION         : {action}")

print("="*60 + "\n")

# ═══════════════════════════════════════════════
# SECTION 10 — UPGRADED DATA LOGGING (FLEXIBLE SCHEMA)
# ═══════════════════════════════════════════════

# 1. Map data to explicit keys using a dictionary. 
log_data = {
    "timestamp": datetime.now(UTC).isoformat(),
    "price": latest['price'],
    "direction": direction,
    "confidence": confidence,
    "grade": grade,
    "total_score": total_score,
    "trend_label": c1_label,
    "cvd_label": c2_label,
    "oi_label": c3_label,
    "spot_label": c4_label,
    "smart_label": c5_label,
    "data_quality": data_quality,
    "expansion_score": expansion_score,
    "classification": classification,
    "expected_move_low": round(expected_move_lower, 2),
    "expected_move_high": round(expected_move_upper, 2),
    "decision_score": decision_score,
    "setup_type": setup_type,
    "trade_status": trade_status,
    "confirmation": confirmation_status,
    "action": action,
    "version": VERSION,
    "stable_bull": round(stable_bull_trigger, 2),
    "stable_bear": round(stable_bear_trigger, 2),
    "bull_power_ratio": round(bull_power_ratio, 3),
    "bear_power_ratio": round(bear_power_ratio, 3)
}

current_headers = list(log_data.keys())
file_exists = os.path.exists(log_file) and os.path.getsize(log_file) > 0
write_headers = not file_exists

# 2. Schema Protection Check
if file_exists:
    try:
        with open(log_file, "r", newline="") as f:
            reader = csv.reader(f)
            existing_headers = next(reader, [])
            
        # If the file's headers don't match the code's headers, back it up.
        if existing_headers != current_headers:
            backup_name = log_file.replace(".csv", f"_backup_{int(time.time())}.csv")
            os.rename(log_file, backup_name)
            print(f"⚠️ {C_YELLOW}CSV schema change detected. Old log backed up to: {backup_name}{C_RESET}")
            write_headers = True
    except Exception as e:
        print(f"⚠️ {C_RED}Error verifying CSV schema: {e}. Starting fresh log.{C_RESET}")
        write_headers = True

# 3. Write data using DictWriter
with open(log_file, "a", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=current_headers)
    if write_headers:
        writer.writeheader()
    writer.writerow(log_data)