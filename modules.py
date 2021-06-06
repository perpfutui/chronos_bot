from retry import *
from exit_after import *
from dotenv import load_dotenv
import os
from os.path import join, dirname
from web3 import Web3
from eth_account import Account
import time
import datetime
import json
import requests
import urllib
from enum import Enum
import pandas as pd
import random


# VARIABLES HERE:
RANDOMIZE = False
DEFAULT_GAS_SPEED = 'average' #fast, average, slow
ALLOW_UNPROFITABLE_TRANSACTION = False

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
    tries: int
    trailingData: dict

    def __str__(self):
        disprice = 0
        if self.orderType == OrderType.LIMIT.value:
            disprice = self.limitPrice
        elif self.orderType == OrderType.STOPMARKET.value or self.orderType == OrderType.STOPLIMIT.value:
            disprice = self.stopPrice
        return "Order [%s] %s %.5f %s @ $%.2f" % (self.orderId, 'BUY' if self.orderSize>0 else 'SELL', abs(self.orderSize), self.asset.name, disprice)

    def __init__(self, assets, id, trader, asset, limitPrice, stopPrice, orderSize, orderType,
        collateral, leverage, slippage, tipFee, expiry, reduceOnly, stillValid, trailingData):
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
        self.tries = 0
        self.trailingData = trailingData


dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)
NODE_URL = os.environ.get('NODE_URL','wss://rpc.xdaichain.com/wss')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY')

w3 = Web3(Web3.WebsocketProvider(NODE_URL, websocket_timeout=120, websocket_kwargs = {"ping_interval":None}))
account = Account.from_key(PRIVATE_KEY)

TRIGGER_LOOP = 30

#pickle
import jsonpickle
def object_write(obj, path):
    with open(path, "w") as f:
        f.write(jsonpickle.encode(obj))

def object_read(path):
    with open(path, "r") as f:
        encoded = f.read()
    return jsonpickle.decode(encoded)

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
LOB = w3.eth.contract(address='0x369287aD9acf4b872F4D6636446D834e73BD41Fd', abi=json.load(open('abi/LimitOrderBook.abi.json','r')))

if w3.isConnected() == True:
    print("Connected with user %s" % account.address)
    time.sleep(1)
else:
    print("The bot can't connect to xDAI")
    quit()

APEX_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/abdullathedruid/apex-keeper"
PERP_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/perpetual-protocol/perp-position-subgraph"
PERP_LIMIT_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/abdullathedruid/perp-limit"

@retry(Exception)
def get_orders():
    global orders
    query = """
    {
      orders(first: 1000, orderBy: tipFee, orderDirection:desc, where:{filled:false, stillValid:true}) {
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
        trailingData {
            id
            witnessPrice
            snapshotTimestamp
            snapshotCreated
            snapshotLastUpdated
        }
      }
    }"""
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
        ass = next((asset for asset in assets if amm["address"].lower() == asset.address.lower() ),"didnt find lol")
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
        ammPositions {
          amm
          positionSize
        }
      }
    }"""
    resp = requests.post(APEX_SUBGRAPH, json={"query": query})
    data = resp.json()
    account_balances = data["data"]["smartWallets"]

@retry(Exception)
def get_trailing_orders():
    global trailing_orders
    #Will need updating when > 1000 trailing orders
    query = """
    {
    trailingOrders(first: 1000) {
    id
    witnessPrice
    snapshotTimestamp
    snapshotCreated
    snapshotLastUpdated
      }
    }
    """
    resp = requests.post(APEX_SUBGRAPH, json={"query": query})
    data = resp.json()
    trailing_orders = data['data']['trailingOrders']

@retry(Exception)
def get_trigger_update(order):
    trail_order = order.trailingData
    if order != 'None':
        last_updated = trail_order['snapshotTimestamp']
        if (int(last_updated)+10*60) < time.time():
            amm = order.asset.address
            RI = trail_order['snapshotLastUpdated']
            price = trail_order['witnessPrice']
            q = '{reserveSnapshottedEvents(first: 1,orderBy: price, orderDirection: asc, where:{amm:"%s", reserveIndex_gt: "%s", price_lte: "%s"})' % (amm,RI,price) if order.orderSize > 0 else '{reserveSnapshottedEvents(first: 1,orderBy: price, orderDirection: desc, where:{amm:"%s", reserveIndex_gt: "%s", price_gte: "%s"})' % (amm,RI,price)
            q = q + '''{
            id
            amm
            blockNumber
            blockTimestamp
            reserveIndex
            price
            }
            }'''
            resp = requests.post(PERP_LIMIT_SUBGRAPH, json={"query": q})
            data = resp.json()
            if len(data["data"]["reserveSnapshottedEvents"]) > 0:
                reserve_index = data["data"]["reserveSnapshottedEvents"][0]["reserveIndex"]
                poke_order(order.orderId, reserve_index,order.tipFee/2)
        else:
            pass
    else:
        pass

def isPos(num):
    if num>=0:
        return True
    elif num<0:
        return False


def can_be_executed(order):
    global account_balances



    if order.stillValid == False:
        return False

    if int(order.expiry) < time.time() and int(order.expiry)!=0:
        return False


    account = [account for account in account_balances if account['owner'] == order.trader][0]
    trader_account_balance = int(account['balance'])/1e6

    currentSize = 0
    for ass in account['ammPositions']:
        if ass['amm'].lower() == order.asset.address.lower():
            currentSize = float(ass['positionSize'])/1e18

    if order.collateral > trader_account_balance: #the user does not have enough money for the order outright so first check if its a reduce order
        exchangedSize = order.orderSize
        newSize = currentSize + exchangedSize

        if isPos(currentSize) == isPos(exchangedSize): #this order will increase size of position
            return False

        if abs(exchangedSize) > abs(currentSize): #this is a close + open reverse order
            newCollateralNeeded = order.collateral*(abs(exchangedSize) - 2*abs(currentSize))/abs(exchangedSize)
            if newCollateralNeeded < 0:
                newCollateralNeeded = 0
            if newCollateralNeeded > trader_account_balance:
                return False

        else: #this is reduce order -> should always be able to happen
            pass

    if order.reduceOnly:
        exchangedSize = order.orderSize

        if isPos(currentSize) == isPos(exchangedSize): #this order will increase size of position
            return False
        if currentSize == 0:
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

    if order.orderId == 275:
        return False

    return True

def execute_order(order_id, maxFee):
    print('Executing order %s' % order_id)
    send_tx(LOB.functions.execute(order_id),maxFee)

def poke_order(order_id,reserve_index, maxFee):
    print('Poking order %s with %s' % (order_id,reserve_index))
    send_tx(LOB.functions.pokeContract(order_id,int(reserve_index)),maxFee)

@exit_after(30)
def send_tx(fn, maxFee=0.01):
    gasprices = requests.get("https://blockscout.com/xdai/mainnet/api/v1/gas-price-oracle").json()
    global globals
    globals = object_read('pickle.data')
    globals['gas_multiplier'] = min(globals['gas_multiplier'] * 1.25, 1000)
    object_write(globals,'pickle.data')
    nonce = w3.eth.getTransactionCount(account.address)
    tx = fn.buildTransaction({
        'from': account.address,
        'nonce': nonce,
        'value': 0,
    })
    estimate = int(1.25*w3.eth.estimate_gas(tx))
    tx['gasPrice'] = gasprices[DEFAULT_GAS_SPEED]*1e9
    tx['gas']=estimate
    if ALLOW_UNPROFITABLE_TRANSACTION:
        MAX_ALLOWED_COST = 1000*1e9 #1000 gwei is max
    else:
        MAX_ALLOWED_COST = int(maxFee * 666 * 1e9)#assume gasLimit of 1.5M
    tx['gasPrice'] = min(MAX_ALLOWED_COST, int(tx['gasPrice'] * globals['gas_multiplier'])) #max tx cost less than bot fee
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    hash = w3.toHex(w3.keccak(signed_tx.rawTransaction))
    result = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    print('Transaction sent: %s' % hash)
    print('Waiting for confirmation...')
    tx_receipt = w3.eth.wait_for_transaction_receipt(result)
    success = bool(tx_receipt['status'])
    if success:
        print('Transaction confirmed - Block: %s   Gas used: %s' % (tx_receipt['blockNumber'], tx_receipt['gasUsed']))
        globals['gas_multiplier'] = 1
        object_write(globals,'pickle.data')
    else:
        print('Transaction failed')
    return success


timer = -1

def loop():
    global timer, globals, orders
    timer += 1
    print('Looping at',datetime.datetime.now())
    get_prices()
    get_balances()
    get_orders()
    if RANDOMIZE:
        random.shuffle(orders)
    for order in orders:
        if can_be_executed(order):
            execute_order(order.orderId,order.tipFee)
        if timer % TRIGGER_LOOP == 0 and order.trailingData:
            get_trigger_update(order)
