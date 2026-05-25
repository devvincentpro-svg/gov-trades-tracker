import hashlib
import re

AMOUNT_MAP = {
    "$1,001 - $15,000":    (1001, 15000),
    "$15,001 - $50,000":   (15001, 50000),
    "$50,001 - $100,000":  (50001, 100000),
    "$100,001 - $250,000": (100001, 250000),
    "$250,001 - $500,000": (250001, 500000),
    "$500,001 - $1,000,000": (500001, 1000000),
    "$1,000,001 - $5,000,000": (1000001, 5000000),
    "$5,000,001 - $25,000,000": (5000001, 25000000),
    "$25,000,001 - $50,000,000": (25000001, 50000000),
}


def parse_amount(raw: str):
    if not raw:
        return None, None
    raw = raw.strip()
    if raw in AMOUNT_MAP:
        return AMOUNT_MAP[raw]
    # try to extract numbers
    nums = re.findall(r"[\d,]+", raw)
    nums = [int(n.replace(",", "")) for n in nums]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def normalize_type(raw: str) -> str:
    if not raw:
        return "unknown"
    raw = raw.lower()
    if "purchase" in raw or "buy" in raw:
        return "buy"
    if "sale" in raw or "sell" in raw or "sold" in raw:
        return "sell"
    if "exchange" in raw:
        return "exchange"
    return raw.strip()


def make_id(politician: str, ticker: str, trade_date: str, trade_type: str) -> str:
    key = f"{politician}|{ticker}|{trade_date}|{trade_type}".lower()
    return hashlib.md5(key.encode()).hexdigest()


def clean_ticker(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip().upper()
    # remove common non-ticker values
    if raw in ("N/A", "--", "NA", "", "NONE"):
        return ""
    return raw
