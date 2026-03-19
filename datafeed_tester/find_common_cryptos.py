import requests
import pandas as pd
import time

print("🚀 Recherche des paires communes aux 4 exchanges...")
print("="*70)

# Liste des cryptos à chercher
CRYPTOS_TO_CHECK = """Bitcoin
Ethereum
Solana
XRP
BNB
Zcash
Dogecoin
Chainlink
Sui
Cardano
Avalanche
Litecoin
Bitcoin Cash
TRON
Pepe
Hyperliquid
Uniswap
Ethena
Monad
Tether Gold
Aster
Yooldo Games
Aave
Shiba Inu
Fartcoin
NEAR Protocol
Plasma
Official Trump
Hedera
Polkadot
Stellar
Sapien
Virtuals Protocol
Bittensor
Dash
Monero
Pudgy Penguins
WhiteBIT Coin
KOGE
Filecoin
Pump.fun
Curve DAO
dogwifhat
World Liberty Financial
Arbitrum
Solar
BOB (Build on Bitcoin)
Internet Computer
Turbo
Mantle
Humanity
Aptos
Worldcoin
ZIGChain
Toncoin
Artificial Superintelligence Alliance
Solayer
Bonk
THORChain
Basic Attention
Celestia
Giggle Fund
POL (ex-MATIC)
Starknet
GaiAI
Momentum
pippin
Kite
PancakeSwap
Optimism
Ondo
Injective
Sahara AI
Avalon
Recall
Particle Network
Merlin Chain
Sei
AINFT
Lido DAO
Bitget Token
Lombard
Zora
Pendle
Allora
Ethereum Classic
JUST
Meteora
GALA
EigenCloud (prev. EigenLayer)
Horizen
Ethereum Name Service
Ether.fi
FLOKI
Linea
ZKsync
Tensor
Cosmos Hub
Render
Apro
Raydium
Story
Irys
Jupiter Perpetuals Liquidity Provider Token
MYX Finance
RedStone
Compound
MetaArena
DoubleZero
LayerZero
Avantis
Neiro
Falcon Finance
Lisk
Algorand
Sonic
Anoma
Tellor Tributes
BSquared Network
Grass
Fluid
XDC Network
Berachain
Yield Basis
OKB
Brett
Arweave
Resolv
0G
Audiera
Boundless
ApeCoin
Kaspa
The Sandbox
Orca
Animecoin
SkyAI
Ape and Pepe
Useless Coin
Popcat
Ancient8
Nexpace
Wormhole
MemeCore
1INCH
Quant
BitTorrent
Alchemist AI
Aerodrome Finance
Maple Finance
The Graph
OVERTAKE
Axie Infinity
Bitlight
Hyperlane
Spark
Jupiter
DeAgentAI
Sky
Vaulta
My Neighbor Alice
Bio Protocol
Rayls
Arkham
Core
SPX6900
Pieverse
Lagrange
MX
ORDI
Chiliz
Jelly-My-Jelly
VeChain
Rain
ConstitutionDAO
Decentraland
Trust Wallet
MANTRA
Peanut the Squirrel
JasmyCoin
Plume
Moo Deng
Tezos
Velo
Mask Network
ChainOpera AI
tokenbot
Babylon
Pyth Network
AI Rig Complex
Fasttoken
Theta Network
Unibase
Baby Shark Universe
Ultima
Cronos
Vana
Immutable
XYO Network
HOME
Pi Network
Waves
aixbt
BounceBit
XT.com
Bitcoin SV
AWE Network
BOOK OF MEME
Synthetix
BUILDon
SuperVerse
ZEROBASE
WINkLink
HarryPotterObamaSonic10Inu (ETH)
Succinct
Jito
Drift Protocol
Aethir
CYBER
Zerebro
DeepBook
OriginTrail
Walrus
Zebec Network
Non-Playable Coin
World Mobile Token
Intuition
yearn.finance
Sushi
Sun Token
Celo
Morpho
AB
Corn
IOTA
SOON
cat in a dogs world
peaq
Yield Guild Games
NEO
Canton
Onyxcoin
Caldera
Stacks
Reserve Rights
Propy
Banana For Scale
IOST
Huma Finance
KernelDAO
Dogs
Snek
Movement
NEXO
CARV
Conflux
Comedian
Moca Network
GMT
io.net
Holoworld
Mog Coin
Renzo
Toshi
Convex Finance
Memecoin
Creditcoin
MEET48
KAITO
Just a chill guy
GoMining Token
Qtum
Kamino
Surge
YZY
Solv Protocol
Ika
Solidus Ai Tech
Mina Protocol
Livepeer
Degen
Aergo
Treasure
deBridge
AI Companions
iExec RLC
Api3
Janction
Axelar
Orderly
OG Fan Token
UCHAIN
Verge
SSV Network
Beam
Band
AltLayer
Lista DAO
0x Protocol
SQD
Liquity
Banana Gun
AIOZ Network
Doodles
Syndicate
Maverick Protocol
Decred
Zilliqa
Terra Luna Classic
Somnia
Numeraire
Notcoin
Beldex
Venus
SoSoValue
Sonic SVM
Akash Network
Mira
Kaia
OpenLedger
Terra
Aevo
MultiversX
Metis
Dymension
Nillion
Cobak
Hashflow
Ribbita by Virtuals
Dent
Big Time
Echelon Prime
WeFi
Blur
River
Orbs
EthereumPoW
Flare
GoPlus Security
MovieBloc
Xai
aPriori
Kled AI
COTI
Goatseus Maximus
Usual
Metaplex
RealLink
USX
PHALA
Santos FC Fan Token
Golem
dYdX
Magic Eden
Nomina
SKALE
Baby Doge Coin
GMX
Saga
GRIFFAIN
ZetaChain
FUNToken
Flow
CoW Protocol
Vine
AVA (Travala)
Balancer
Impossible Cloud Network Token
Gnosis
BugsCoin
Bounce
Steem
XPIN Network
FOLKS
Audius
ROAM Token
Avici
Telcoin
Helium
UMA
Sign
Storj
Chia
Taiko
STBL
Ravencoin
GHO
Alchemix
Sophon
affine
INFINIT
Manta Network
Kusama
Vision
Alchemy Pay"""

# Convertir en liste et nettoyer
crypto_names = [name.strip() for name in CRYPTOS_TO_CHECK.split('\n') if name.strip()]

print(f"📊 {len(crypto_names)} cryptos à vérifier")

# Mapping nom -> symbole (on va utiliser CoinGecko pour ça)
print("\n🔍 Récupération des symboles depuis CoinGecko...")

# Récupérer la liste complète des cryptos avec symboles
coins_list_url = "https://api.coingecko.com/api/v3/coins/list"
coins_response = requests.get(coins_list_url)
all_coins = coins_response.json()

# Créer un mapping nom -> symbole
name_to_symbol = {}
for coin in all_coins:
    name = coin.get('name', '').lower()
    symbol = coin.get('symbol', '').upper()
    name_to_symbol[name] = symbol

# Mapper les noms de la liste
crypto_symbols = []
unmapped = []

for name in crypto_names:
    name_lower = name.lower()
    if name_lower in name_to_symbol:
        crypto_symbols.append(name_to_symbol[name_lower])
    else:
        unmapped.append(name)

print(f"✅ {len(crypto_symbols)} symboles trouvés")
if unmapped:
    print(f"⚠️  {len(unmapped)} non trouvés: {unmapped[:10]}...")

time.sleep(2)

# Configuration des exchanges
EXCHANGES = {
    "bybit": {"id": "bybit_spot", "quote": "USDT"},
    "binance": {"id": "binance", "quote": "USDT"},
    "kraken": {"id": "kraken", "quote": "USD"},
    "coinbase": {"id": "gdax", "quote": "USD"}
}

MIN_VOLUME = 100000  # $100k minimum

# Récupérer les paires de chaque exchange
exchange_cryptos = {}

for exchange_name, config in EXCHANGES.items():
    print(f"\n📊 {exchange_name.upper()} ({config['quote']})...")
    
    available_bases = set()
    
    for page in range(1, 4):  # 3 pages max
        try:
            url = f"https://api.coingecko.com/api/v3/exchanges/{config['id']}/tickers"
            params = {
                "page": page,
                "order": "volume_desc"
            }
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 429:
                print(f"   Rate limit, pause...")
                time.sleep(60)
                response = requests.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                break
            
            data = response.json()
            tickers = data.get('tickers', [])
            
            if not tickers:
                break
            
            for ticker in tickers:
                base = ticker.get("base", "").upper()
                target = ticker.get("target", "").upper()
                volume = ticker.get("converted_volume", {}).get("usd", 0)
                
                # Mapping Kraken
                if exchange_name == "kraken" and base == "XBT":
                    base = "BTC"
                
                if target == config['quote'] and volume >= MIN_VOLUME:
                    available_bases.add(base)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"   Erreur: {str(e)[:50]}")
            break
    
    exchange_cryptos[exchange_name] = available_bases
    print(f"   ✅ {len(available_bases)} cryptos disponibles")

print("\n" + "="*70)
print("🔍 RECHERCHE DES PAIRES COMMUNES")
print("="*70)

# Trouver les cryptos disponibles sur les 4 exchanges ET dans votre liste
crypto_symbols_set = set(crypto_symbols)

common_on_all_4 = set.intersection(*exchange_cryptos.values())
final_list = common_on_all_4.intersection(crypto_symbols_set)

print(f"\n✅ {len(final_list)} cryptos de votre liste présentes sur les 4 exchanges:")
print()

sorted_list = sorted(final_list)
for i, crypto in enumerate(sorted_list, 1):
    print(f"{i:3}. {crypto}")

# Sauvegarder
output_file = "common_cryptos_4_exchanges.csv"

# Créer un DataFrame avec détails
common_data = []
for crypto in sorted_list:
    # Retrouver le nom
    name = next((n for n in crypto_names if name_to_symbol.get(n.lower()) == crypto), crypto)
    common_data.append({
        "symbol": crypto,
        "name": name,
        "on_bybit": crypto in exchange_cryptos["bybit"],
        "on_binance": crypto in exchange_cryptos["binance"],
        "on_kraken": crypto in exchange_cryptos["kraken"],
        "on_coinbase": crypto in exchange_cryptos["coinbase"]
    })

df = pd.DataFrame(common_data)
df.to_csv(output_file, index=False)

print(f"\n💾 Fichier sauvegardé : {output_file}")
print(f"📁 Chemin : /Users/vladimirkronos/Downloads/Projet-Kronos-main/datafeed_tester/{output_file}")
