from decimal import Decimal


def calculate_total(unit_price, quantity, discount_percent):
    subtotal = Decimal(str(unit_price)) * quantity
    return subtotal - Decimal(str(discount_percent))


if __name__ == "__main__":
    total = calculate_total("100.00", 2, 10)
    print(f"订单总额: {total:.2f} 元")
