"""calculator: one method per tool of the app. No state; results are pure functions of the arguments.
calculate: digits, + - * / ( ) . and % only (a number directly followed by % with no operand after it is a percentage, e.g.
"200*15%" = 30; otherwise % is modulo), evaluated with ast. convert_unit: length (mm, cm, m, km), mass (g, kg),
volume (ml, l), temperature (c, f)."""
from __future__ import annotations

import ast
import math
import operator
import re

from .base import App, read

_ALLOWED = set("0123456789+-*/().% ")
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
# unit -> (dimension, factor to the base unit: m, kg, l)
_UNITS = {"mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0),
          "g": ("mass", 0.001), "kg": ("mass", 1.0), "ml": ("volume", 0.001), "l": ("volume", 1.0),
          "c": ("temperature", None), "f": ("temperature", None)}
_ALIAS = {"°c": "c", "độ c": "c", "celsius": "c", "°f": "f", "độ f": "f", "fahrenheit": "f", "lít": "l", "lit": "l",
          "mét": "m", "met": "m", "gam": "g", "gram": "g", "kí": "kg", "ki lô gam": "kg", "kilogram": "kg", "ki lô mét": "km", "kilomet": "km"}


def _num(v):
    v = round(v, 6)
    return int(v) if float(v).is_integer() else v


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval(node.operand))
    raise ValueError("biểu thức không hợp lệ")


def _unit(u):
    u = str(u or "").strip().lower()
    return _ALIAS.get(u, u)


class Calculator(App):
    name = "calculator"

    @read
    def calculate(self, expression=None, **_):
        expression = str(expression or "")
        expr = expression.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/").replace(":", "/")
        if not set(expr) <= _ALLOWED:
            return self.noop("biểu thức chỉ được gồm số và + - * / ( ) . %")
        expr = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(.])", r"(\1/100)", expr)  # trailing percent sign -> /100
        try:
            value = _num(_eval(ast.parse(expr, mode="eval")))
        except ZeroDivisionError:
            return self.noop("chia cho 0")
        except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
            return self.noop("biểu thức không hợp lệ")
        except ArithmeticError:  # OverflowError: number too large
            return self.noop("kết quả quá lớn")
        if not math.isfinite(value):
            return self.noop("kết quả quá lớn")
        return {"ok": True, "expression": expression, "value": value}

    @read
    def convert_unit(self, value=None, from_unit=None, to_unit=None, **_):
        fu, tu = _unit(from_unit), _unit(to_unit)
        if fu not in _UNITS or tu not in _UNITS:
            return self.noop(f"đơn vị không hỗ trợ: {from_unit if fu not in _UNITS else to_unit!r}")
        (fd, ff), (td, tf) = _UNITS[fu], _UNITS[tu]
        if fd != td:
            return self.noop(f"không quy đổi được {fu} sang {tu}")
        if fd == "temperature":
            out = value if fu == tu else (value * 9 / 5 + 32 if fu == "c" else (value - 32) * 5 / 9)
        else:
            out = value * ff / tf
        try:
            out = _num(out)
        except (ArithmeticError, ValueError):
            out = float("inf")
        if not math.isfinite(out):
            return self.noop("giá trị quá lớn")
        return {"ok": True, "value": out, "unit": tu, "from_value": value, "from_unit": fu}
