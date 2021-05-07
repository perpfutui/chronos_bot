from retry import *
from dotenv import load_dotenv
import os
from os.path import join, dirname
from web3 import Web3
from eth_account import Account
import time
import json
import requests
import urllib
from enum import Enum
import pandas as pd

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


dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)
NODE_URL = os.environ.get('NODE_URL','wss://rpc.xdaichain.com/wss')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY')

w3 = Web3(Web3.WebsocketProvider(NODE_URL, websocket_timeout=120, websocket_kwargs = {"ping_interval":None}))

account = Account.from_key(PRIVATE_KEY)

#Get all AMMs
def get_amms():
    output = []
    with urllib.request.urlopen('https://metadata.perp.exchange/production.json') as url:
        data = json.loads(url.read().decode())
        contracts = data['layers']['layer2']['contracts']
        for contract in contracts:
            if data['layers']['layer2']['contracts'][contract]['name'] == 'Amm':
                output.append(Asset(contract[0:-4], data['layers']['layer2']['contracts'][contract]['address']))
    return output
assets = get_amms()

#Instantiate contracts:
LOB = w3.eth.contract(address='0x02e7B722E178518Ae07a596A7cb5F88B313c453a', abi=json.load(open('abi/LimitOrderBook.abi.json','r')))

if w3.isConnected() == True:
    print("Connected with user %s" % account.address)
    time.sleep(1)
else:
    print("The bot can't connect to xDAI")
    quit()

APEX_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/abdullathedruid/apex-keeper"
PERP_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/perpetual-protocol/perp-position-subgraph"

@retry(Exception)
def get_orders():
    global orders
    query = """
    {
      orders(first: 1000, orderBy: tipFee, orderDirection:desc, where:{filled:false, stillValid:true, expiry_gt:"%s"}) {
        id
        trader
        asset
        limitPrice
        stopPrice
        orderSize
        orderType
        collateral
        leverage
        slippage
        tipFee
        expiry
        reduceOnly
        stillValid
      }
    }""" % (int(time.time()))
    resp = requests.post(APEX_SUBGRAPH, json={"query":query})
    data = resp.json()
    orders = []
    for order in data["data"]["orders"]:
        orders.append(Order(assets,**order))

@retry(Exception)
def get_prices():
    global assets
    query = """{
        amms(first:100) {
            address
            quoteAssetReserve
            baseAssetReserve
        }
    }"""
    resp = requests.post(PERP_SUBGRAPH, json={"query": query})
    data = resp.json()
    for amm in data["data"]["amms"]:
        ass = next((asset for asset in assets if amm["address"] == asset.address.lower() ),"didnt find lol")
        if float(amm["baseAssetReserve"])>0 :
            ass.price = float(amm["quoteAssetReserve"])/float(amm["baseAssetReserve"])
        else:
            pass
            #need to get price from contract

@retry(Exception)
def get_balances():
    global account_balances
    # We need to change this when there are more than 1000 wallets
    query = """{
      smartWallets(orderBy:balance, orderDirection: desc, first:1000) {
        id
        owner
        balance
      }
    }"""
    resp = requests.post(APEX_SUBGRAPH, json={"query": query})
    data = resp.json()
    account_balances = data["data"]["smartWallets"]

def can_be_executed(order):
    global account_balances

    if order.stillValid == False:
        return False

    if int(order.expiry) < time.time() and int(order.expiry)!=0:
        return False

    trader_account_balance = int([account['balance'] for account in account_balances if account['owner'] == order.trader][0])

    if order.collateral > (trader_account_balance/1e6):
        return False

    if order.orderType == OrderType.LIMIT.value:
        if order.orderSize > 0: #limit buy
            if order.asset.price > order.limitPrice:
                return False
        elif order.orderSize < 0: #limit sell
            if order.asset.price < order.limitPrice:
                return False
        else:
            return False

    if order.orderType == OrderType.STOPMARKET.value or order.orderType == OrderType.TRAILINGSTOPMARKET.value:
        if order.orderSize > 0: #stop buy
            if order.asset.price < order.stopPrice:
                return False
        elif order.orderSize < 0: #stop sell
            if order.asset.price > order.stopPrice:
                return False
        else:
            return False

    if order.orderType == OrderType.STOPLIMIT.value or order.orderType == OrderType.TRAILINGSTOPLIMIT.value:
        if order.orderSize > 0: #stoplimit buy
            if order.asset.price < order.stopPrice:
                return False
            if order.asset.price > order.limitPrice:
                return False
        elif order.orderSize < 0: #stoplimit sell
            if order.asset.price > order.stopPrice:
                return False
            if order.asset.price < order.limitPrice:
                return False
        else:
            return False

    return True

def execute_order(order_id):
    print('Executing order %s' % order_id)
    send_tx(LOB.functions.execute(order_id))

def send_tx(fn):
    nonce = w3.eth.getTransactionCount(account.address)
    tx = fn.buildTransaction({
        'from': account.address,
        'nonce': nonce,
        'value': 0,
        'gasPrice': w3.toWei('1','gwei'),
    })
    estimate = int(1.1*w3.eth.estimate_gas(tx))
    tx['gas']=estimate
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    result = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    print('Transaction sent: %s' % w3.toHex(w3.keccak(signed_tx.rawTransaction)))
    print('Waiting for confirmation...')
    tx_receipt = w3.eth.wait_for_transaction_receipt(result)
    success = bool(tx_receipt['status'])
    if success:
        print('Transaction confirmed - Block: %s   Gas used: %s' % (tx_receipt['blockNumber'], tx_receipt['gasUsed']))
    else:
        print('oh no')
    return success


def loop():
    get_prices()
    get_balances()
    get_orders()
    for order in orders:
        if can_be_executed(order):
            execute_order(order.orderId)
