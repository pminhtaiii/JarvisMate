"""Conservative Vietnamese numbers and explicit units; no transcript rewriting."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


_DIGITS = {word: n for n, words in enumerate((
    ("không",), ("một", "mốt"), ("hai",), ("ba",), ("bốn", "tư"),
    ("năm", "lăm"), ("sáu",), ("bảy",), ("tám",), ("chín",))) for word in words}
_SCALES = {"tỷ": 10**9, "tỉ": 10**9, "triệu": 10**6, "nghìn": 1000, "ngàn": 1000}


def _group(words: list[str]) -> int:
    if len(words) == 1:
        if words[0].isdigit():
            return int(words[0])
        if words[0] in _DIGITS:
            return _DIGITS[words[0]]
    total = 0
    if len(words) >= 2 and words[0] in _DIGITS and words[1] == "trăm":
        total, words = _DIGITS[words[0]] * 100, words[2:]
        if not words:
            return total
        if words[0] in {"linh", "lẻ"}:
            if len(words) != 2 or words[1] not in _DIGITS:
                raise ValueError("Invalid units after hundreds")
            return total + _DIGITS[words[1]]
    if words and words[0] == "mười":
        tens, words = 10, words[1:]
    elif len(words) >= 2 and words[0] in _DIGITS and _DIGITS[words[0]] >= 2 and words[1] == "mươi":
        tens, words = _DIGITS[words[0]] * 10, words[2:]
    else:
        raise ValueError("Unsupported number grammar")
    if not words:
        return total + tens
    if len(words) == 1 and words[0] in _DIGITS and _DIGITS[words[0]] > 0:
        return total + tens + _DIGITS[words[0]]
    raise ValueError("Invalid number suffix")


def number(value: str, *, grouping: bool | None = None) -> Decimal:
    """Parse numbers; grouping=True selects Vietnamese money notation.

    False treats a single separator as decimal (e.g. temperature or an explicit
    scale coefficient). None rejects a single ambiguous three-digit separator.
    Multiple explicit thousands groups remain unambiguous when grouping is allowed.
    """
    if len(value) > 512:
        raise ValueError("Number too long")
    value = clean(value)
    sign = 1
    for prefix in ("âm ", "trừ ", "-"):
        if value.startswith(prefix):
            sign, value = -1, value[len(prefix):]
            break
    if re.fullmatch(r"\d+([.,]\d+)?", value) or re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", value):
        ambiguous = re.fullmatch(r"\d{1,3}([.,])\d{3}", value)
        grouped = re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", value)
        if ambiguous and (grouping is None or grouping is True and ambiguous[1] == ","):
            raise ValueError("Ambiguous numeric separator")
        if grouped and grouping is not False:
            value = value.replace(".", "")
        try:
            return sign * Decimal(value.replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError("Invalid numeric literal") from exc
    # Parse a decimal coefficient before multiplying its explicit scale, so
    # 'một phẩy năm triệu' and '1,5 triệu' follow the same arithmetic.
    if " phẩy " in value and not any(word in _SCALES for word in value.split()):
        whole, fraction = value.split(" phẩy ", 1)
        digits = fraction.split()
        if not digits or any(w not in _DIGITS for w in digits):
            raise ValueError("Fraction requires individual digits")
        return sign * (number(whole, grouping=False) + Decimal("0." + "".join(str(_DIGITS[w]) for w in digits)))
    words, total, group, previous = value.split(), Decimal(0), [], 10**12
    for index, word in enumerate(words):
        if word not in _SCALES:
            group.append(word)
            continue
        scale = _SCALES[word]
        if scale >= previous or not group:
            raise ValueError("Invalid scale order")
        coefficient = number(" ".join(group), grouping=False)
        if coefficient < 0 or coefficient >= 1000:
            raise ValueError("Invalid scale coefficient")
        total += coefficient * scale
        previous, group = scale, []
        if words[index + 1:] == ["rưỡi"]:
            return sign * (total + Decimal(scale) / 2)
    if group:
        tail = _group(group)
        if previous < 10**12 and tail >= previous:
            raise ValueError("Invalid scale remainder")
        total += tail
    elif not words:
        raise ValueError("Empty number")
    return sign * total


def duration_seconds(value: str) -> Decimal:
    """Explicit descending units; support halves and compound durations."""
    value = clean(value)
    if len(value) > 512:
        raise ValueError("Duration too long")
    pattern = re.compile(r"(.+?)\s+(ngày|giờ|tiếng|phút|giây)( rưỡi)?(?=\s|$)")
    total, previous, end = Decimal(0), 10**9, 0
    for match in pattern.finditer(value):
        if match.start() != end:
            raise ValueError("Unsupported duration grammar")
        count_text = match[1].strip()
        if end and count_text.startswith("và "):
            count_text = count_text[3:]
        count = Decimal("0.5") if count_text == "nửa" else number(count_text, grouping=False)
        unit = {"ngày": 86400, "giờ": 3600, "tiếng": 3600, "phút": 60, "giây": 1}[match[2]]
        if unit >= previous or count < 0 or count_text == "nửa" and match[3]:
            raise ValueError("Invalid duration order or value")
        total += (count + (Decimal("0.5") if match[3] else 0)) * unit
        previous, end = unit, match.end()
        # finditer's next match consumes the separating space in its count group.
    if end != len(value) or not end:
        raise ValueError("Duration needs explicit units")
    return total


def quantity(value: str, field: str, *, numeric_type: str = "number") -> int | float:
    value = clean(value)
    if field == "amount":
        value = re.sub(r"\s*(đồng|vnd|₫|đ)$", "", value)
    if "temperature" in field:
        value = re.sub(r"\s*(độ c|độ|°c)$", "", value)
    target = (60 if field.endswith("minutes") else 1 if field.endswith("seconds")
              else 3600 if field.endswith("hours") else None)
    if target and re.search(r"\b(ngày|giờ|tiếng|phút|giây)\b", value):
        parsed = duration_seconds(value) / target
    else:
        policy = True if field == "amount" else None if numeric_type == "integer" else False
        parsed = number(value, grouping=policy)
    if not parsed.is_finite():
        raise ValueError("Non-finite quantity")
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)
