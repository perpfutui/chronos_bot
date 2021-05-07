# chronos_bot

Please create virtual environment
`python3 -m venv bot`

Please activate virtual environment
`source bot/bin/activate`

Install libraries
`pip3 install -r requirements.txt`

Set up env variables as follows by creating a .env file:

`NODE_URL=wss://rpc.xdaichain.com/wss` or alternate websocket provider

`PRIVATE_KEY=YOURPRIVATEKEYGOESHERE`

Run the bot in command line:
`./forever.py app.py`
