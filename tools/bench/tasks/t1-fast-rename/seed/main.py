from calc import total_price, discount


def main():
    items = [("pen", 1.5, 4), ("book", 12.0, 1)]
    t = total_price(items)
    print("total:", t)
    print("after 10% off:", discount(total_price(items), 10))


if __name__ == "__main__":
    main()
