from decimal import Decimal as Dec, ROUND_DOWN


class Decimal(Dec):
    def __new__(cls, value="0", context=None):
        d = Dec.__new__(cls, value, context)
        return d.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def __add__(self, other, context=None):
        res = super(Decimal, self).__add__(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def __sub__(self, other, context=None):
        res = super(Decimal, self).__sub__(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def __mul__(self, other, context=None):
        res = super(Decimal, self).__mul__(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def __truediv__(self, other, context=None):
        res = super(Decimal, self).__truediv__(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def _divide(self, other, context=None):
        res = super(Decimal, self)._divide(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)

    def __divmod__(self, other, context=None):
        res = super(Decimal, self).__divmod__(self, other, context)
        return res.quantize(Dec('0.00000001'), rounding=ROUND_DOWN)
