"""
FX rate table for Helios Chemicals Group.
Base currency: USD. All rates express how many USD one unit of the foreign currency buys.
"""

FX_RATES: dict[str, float] = {
    "USD": 1.0,
    "GBP": 1.27,
    "EUR": 1.09,
    "SGD": 0.74,
    "AUD": 0.65,
    "JPY": 0.0067,
}

VALID_CURRENCIES: set[str] = set(FX_RATES.keys())


def get_rate(currency: str) -> float | None:
    """Return the USD conversion rate for a given currency, or None if unsupported."""
    try:
        return FX_RATES.get(currency.upper())
    except Exception:
        return None


def convert_to_usd(amount: float, currency: str) -> float:
    """Convert an amount in the given currency to USD.

    Raises ValueError if the currency is not supported.
    """
    try:
        rate = get_rate(currency)
        if rate is None:
            raise ValueError(f"Unsupported currency: {currency}")
        return round(amount * rate, 2)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"FX conversion failed for {currency}: {exc}") from exc


def is_valid_currency(currency: str) -> bool:
    """Return True if the currency code is supported."""
    try:
        return currency.upper() in VALID_CURRENCIES
    except Exception:
        return False
