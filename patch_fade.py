#!/usr/bin/env python3
"""Quiet follows two closed hours when they oppose the 4h.
Pullback and quiet skip a trade only when basis and funding are both crowded."""
import os
import re
import shutil
import py_compile

TARGET = "main.py"
BACKUP = "main.py.bak_fade"

HELPERS = '''async def btc_hour_fade_side(d4: str) -> str:
    """SELL if two closed BTC hours are red while 4h is still up. BUY for the mirror."""
    d4u = str(d4 or "").upper()
    if d4u not in ("BULL", "BEAR"):
        return ""
    try:
        k = await get_futures_klines_cached(
            symbol=getattr(config, "INDEX_SYMBOL", "BTCUSDT"),
            interval="1h", limit=4, closed_only=True,
        )
    except Exception:
        return ""
    if not k or len(k) < 2:
        return ""
    last = k[-2:]
    red = all(float(x[4]) < float(x[1]) for x in last)
    green = all(float(x[4]) > float(x[1]) for x in last)
    if d4u == "BULL" and red:
        return "SELL"
    if d4u == "BEAR" and green:
        return "BUY"
    return ""


async def crowd_basis_block(symbol: str, side: str, funding_rate: float) -> str:
    """Block only when the contract is rich or cheap AND funding is crowded. One is not enough."""
    side_u = str(side or "").upper()
    if side_u not in ("BUY", "SELL"):
        return ""
    try:
        mark = await client.futures_mark_price(symbol=symbol)
    except Exception as e:
        logger.info(f"crowd basis skip {symbol} | {e}")
        return ""
    if isinstance(mark, list):
        mark = next((m for m in mark if m.get("symbol") == symbol), None)
    if not isinstance(mark, dict):
        return ""
    try:
        mp = float(mark.get("markPrice") or 0)
        ip = float(mark.get("indexPrice") or 0)
    except Exception:
        return ""
    if mp <= 0 or ip <= 0:
        return ""
    basis = (mp - ip) / ip
    rate = float(funding_rate or 0)
    cap = float(getattr(config, "CROWD_BASIS_ABS", 0.0015))
    long_fund = float(getattr(config, "CROWD_FUNDING_LONG", 0.00030))
    short_fund = float(getattr(config, "CROWD_FUNDING_SHORT", -0.00010))
    if side_u == "BUY" and basis > cap and rate > long_fund:
        return f"basis={basis:+.3%} funding={rate * 100:.4f}%"
    if side_u == "SELL" and basis < -cap and rate < short_fund:
        return f"basis={basis:+.3%} funding={rate * 100:.4f}%"
    return ""


'''


def fail(msg):
    shutil.copy2(BACKUP, TARGET)
    print(msg)
    print(f"restored from {BACKUP} — bot file was not changed")


def replace_one(text, old, new, label):
    n = text.count(old)
    if n != 1:
        return text, f"{label} count={n}"
    return text.replace(old, new, 1), None


def main():
    if not os.path.exists(TARGET):
        print(f"STOPPED missing {TARGET}")
        return
    shutil.copy2(TARGET, BACKUP)
    raw = open(TARGET, encoding="utf-8").read()
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if "async def btc_hour_fade_side(" in text or "QUIET_FADE_SIZE_MULT" in text:
        fail("STOPPED fade rules are already in this file")
        return

    insert = (
        "    QUIET_FADE_SIZE_MULT = 0.50\n"
        "    CROWD_BASIS_ABS = 0.0015\n"
        "    CROWD_FUNDING_LONG = 0.00030\n"
        "    CROWD_FUNDING_SHORT = -0.00010\n"
    )
    cfg = re.compile(r"^[ \t]*DAILY_CARRY_FUNDING_SHORT_MIN\s*=\s*-?[0-9.]+.*\n", re.M)
    found = list(cfg.finditer(text))
    if len(found) == 1:
        text = text[:found[0].end()] + insert + text[found[0].end():]
    elif "    QUIET_MOVER_SIZE_MULT = 0.50\n" in text:
        text = text.replace("    QUIET_MOVER_SIZE_MULT = 0.50\n", "    QUIET_MOVER_SIZE_MULT = 0.50\n" + insert, 1)
    else:
        print("config line missing — code defaults still apply")

    pairs = [
        (
            "async def select_momentum_signals() -> Dict[str, dict]:\n",
            HELPERS + "async def select_momentum_signals() -> Dict[str, dict]:\n",
            "helpers",
        ),
        (
            '''    def pack(sym, side, chg, px, atr, dist, body, kind):
        _momentum_stop[sym] = dist
        logger.info(
            f"✅ {kind} {side} {sym} | 24h={chg:+.1f}% body={body:.2f} | 1h={d1} 4h={d4}"
        )
        picks[sym] = {
            "symbol": sym,
            "side": side,
            "entry_price": px,
            "atr": atr if atr > 0 else dist,
            "confidence": 0.74 if kind == "PULLBACK" else 0.72,
            "momentum_rs": True,
            "quiet_mover": kind == "QUIET",
            "chg24": chg,
            "cvd_info": {},
        }
''',
            '''    def pack(sym, side, chg, px, atr, dist, body, kind, fade=False):
        _momentum_stop[sym] = dist
        kind_log = f"{kind} FADE" if fade else kind
        logger.info(
            f"✅ {kind_log} {side} {sym} | 24h={chg:+.1f}% body={body:.2f} | 1h={d1} 4h={d4}"
        )
        picks[sym] = {
            "symbol": sym,
            "side": side,
            "entry_price": px,
            "atr": atr if atr > 0 else dist,
            "confidence": 0.74 if kind == "PULLBACK" else 0.72,
            "momentum_rs": True,
            "quiet_mover": kind == "QUIET",
            "quiet_fade": bool(fade),
            "chg24": chg,
            "cvd_info": {},
        }
''',
            "pack",
        ),
        (
            '''    if d1 in ("BULL", "BEAR") and d4 in ("BULL", "BEAR") and d1 != d4:
        quiet_side = ""
    elif d1 == "NEUTRAL":
        quiet_side = {"BULL": "BUY", "BEAR": "SELL"}.get(d4, "")
    else:
        quiet_side = agreed or {"BULL": "BUY", "BEAR": "SELL"}.get(d1, "")
''',
            '''    fade_side = await btc_hour_fade_side(d4)
    if fade_side:
        quiet_side = fade_side
        logger.info(f"📉 Quiet fade | 4h={d4} → {fade_side} | two closed hours against")
    elif d1 in ("BULL", "BEAR") and d4 in ("BULL", "BEAR") and d1 != d4:
        quiet_side = ""
    elif d1 == "NEUTRAL":
        quiet_side = {"BULL": "BUY", "BEAR": "SELL"}.get(d4, "")
    else:
        quiet_side = agreed or {"BULL": "BUY", "BEAR": "SELL"}.get(d1, "")
''',
            "quiet-side",
        ),
        (
            '        pack(sym, side, chg, px, atr, dist, body, "QUIET")\n',
            '        pack(sym, side, chg, px, atr, dist, body, "QUIET", fade=bool(fade_side and side == fade_side))\n',
            "quiet-pack",
        ),
        (
            '''            "quiet_mover": bool(sig.get("quiet_mover")),
            "chg24": float(sig.get("chg24") or 0),
''',
            '''            "quiet_mover": bool(sig.get("quiet_mover")),
            "quiet_fade": bool(sig.get("quiet_fade")),
            "chg24": float(sig.get("chg24") or 0),
''',
            "signal",
        ),
        (
            '''                ok_idx, why_idx = index_entry_allowed(idx_now, signal.get("side"))
                if not ok_idx:
                    strategy.logger.info(f"🚫 INDEX REJECT MomentumRS {symbol} | {why_idx}")
                    release_pending_claim(symbol, claimed)
                    return False
''',
            '''                ok_idx, why_idx = index_entry_allowed(idx_now, signal.get("side"))
                if not ok_idx and not signal.get("quiet_fade"):
                    strategy.logger.info(f"🚫 INDEX REJECT MomentumRS {symbol} | {why_idx}")
                    release_pending_claim(symbol, claimed)
                    return False
                if signal.get("quiet_fade") and not ok_idx:
                    strategy.logger.info(f"📉 Quiet fade index {symbol} | {why_idx}")
                    why_idx = f"fade {why_idx}"
''',
            "index",
        ),
        (
            '''                if signal.get("quiet_mover"):
                    extra_size_mult = float(getattr(config, "QUIET_MOVER_SIZE_MULT", 0.50))
                else:
                    extra_size_mult = float(getattr(config, "MOMENTUM_RS_SIZE_MULT", 1.0))
''',
            '''                if signal.get("quiet_mover"):
                    extra_size_mult = float(getattr(config, "QUIET_MOVER_SIZE_MULT", 0.50))
                    if signal.get("quiet_fade"):
                        extra_size_mult *= float(getattr(config, "QUIET_FADE_SIZE_MULT", 0.50))
                        strategy.logger.info(f"📉 Quiet fade size {symbol} | ×{extra_size_mult:.2f}")
                else:
                    extra_size_mult = float(getattr(config, "MOMENTUM_RS_SIZE_MULT", 1.0))
''',
            "size",
        ),
        (
            '''            funding = await filters.check_funding_rate(symbol)
            htf = await filters.check_higher_timeframe(symbol)
''',
            '''            funding = await filters.check_funding_rate(symbol)
            if is_mrs:
                crowd = await crowd_basis_block(symbol, signal.get("side"), float(funding.get("rate") or 0))
                if crowd:
                    strategy.logger.info(f"🚫 CROWD {symbol} | {signal.get('side')} {crowd}")
                    release_pending_claim(symbol, claimed)
                    return False
            htf = await filters.check_higher_timeframe(symbol)
''',
            "crowd",
        ),
    ]

    for old, new, label in pairs:
        text, err = replace_one(text, old, new, label)
        if err:
            fail(f"STOPPED {err}")
            return

    if "async def btc_hour_fade_side(" not in text or "quiet_fade" not in text:
        fail("STOPPED fade was not installed")
        return
    open(TARGET, "w", encoding="utf-8").write(text)
    try:
        py_compile.compile(TARGET, doraise=True)
    except Exception as e:
        fail(f"STOPPED compile: {e}")
        return
    print(f"DONE pieces={len(pairs) + 1}")
    print(f"backup={BACKUP}")


if __name__ == "__main__":
    main()
