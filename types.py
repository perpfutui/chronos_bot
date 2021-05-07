class Asset:
    name: str
    address: str
    price: float

    def __str__(self):
        return "%s [%s] price is $%.2f" % (self.name, self.address, self.price)

    def __init__(self, name, address):
        self.name = name
        self.address = address
        self.price = 0

class OrderType(Enum):
    MARKET = 0
    LIMIT = 1
    STOPMARKET = 2
    STOPLIMIT = 3
    TRAILINGSTOPMARKET = 4
    TRAILINGSTOPLIMIT = 5

class Order:
    orderId: int
    trader: str
    asset: Asset
    limitPrice: float
    stopPrice: float
    orderSize: float
    collateral: float
    leverage: float
    slippage: float
    tipFee: float
    expiry: float
    reduceOnly: bool

    def __str__(self):
        disprice = 0
        if self.orderType == OrderType.LIMIT.value:
            disprice = self.limitPrice
        elif self.orderType == OrderType.STOPMARKET.value or self.orderType == OrderType.STOPLIMIT.value:
            disprice = self.stopPrice
        return "Order [%s] %s %.5f %s @ $%.2f" % (self.orderId, 'BUY' if self.orderSize>0 else 'SELL', abs(self.orderSize), self.asset.name, disprice)

    def __init__(self, assets, id, trader, asset, limitPrice, stopPrice, orderSize, orderType,
        collateral, leverage, slippage, tipFee, expiry, reduceOnly, stillValid):
        self.orderId = int(id)
        self.trader = trader
        self.asset = next(x for x in assets if x.address.lower() == asset.lower())
        self.limitPrice = float(limitPrice)/1e18
        self.stopPrice = float(stopPrice)/1e18
        self.orderSize = float(orderSize)/1e18
        self.orderType = int(orderType)
        self.collateral = float(collateral)/1e18
        self.leverage = float(leverage)/1e18
        self.slippage = float(slippage)/1e18
        self.tipFee = float(tipFee)/1e18
        self.expiry = expiry
        self.reduceOnly = reduceOnly
        self.stillValid = stillValid
