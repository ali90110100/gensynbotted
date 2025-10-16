from flask import Flask, render_template, request, jsonify
from web3 import Web3
import requests
from datetime import datetime
import pytz
import os

app = Flask(__name__)

# Gensyn Testnet Constants
ALCHEMY_RPC = "https://gensyn-testnet.g.alchemy.com/public"
CONTRACT_ADDRESS = "0xFaD7C5e93f28257429569B854151A1B8DCD404c2"

ABI = [
    {
        "name": "getPeerId",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "eoaAddresses", "type": "address[]"}],
        "outputs": [{"name": "", "type": "string[][]"}]
    }
]

class GensynTracker:
    def __init__(self):
        try:
            self.w3 = Web3(Web3.HTTPProvider(ALCHEMY_RPC, request_kwargs={'timeout': 60}))
            if self.w3.is_connected():
                print("Connected to Ethereum network")
                self.contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(CONTRACT_ADDRESS), 
                    abi=ABI
                )
            else:
                print("Failed to connect to Ethereum network")
                self.contract = None
        except Exception as e:
            print(f"Initialization error: {e}")
            self.contract = None
    
    def get_peer_ids_from_eoa(self, eoa_address):
        """Get peer IDs for a given EOA address"""
        try:
            if not self.contract:
                return []
            
            # Validate EOA address
            if not Web3.is_address(eoa_address):
                return []
                
            checksum_address = Web3.to_checksum_address(eoa_address)
            result = self.contract.functions.getPeerId([checksum_address]).call()
            return result[0] if result else []
        except Exception as e:
            print(f"Error getting peer IDs: {e}")
            return []
    
    def fetch_rank_data(self, peer_ids):
        """Fetch node statistics from Gensyn API"""
        if not peer_ids:
            return None
            
        url = "https://gswarm.dev/api/user/data"
        headers = {"Content-Type": "application/json"}
        payload = {"peerIds": peer_ids}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"API returned status {response.status_code}")
                return None
        except Exception as e:
            print(f"API Error: {e}")
            return None
    
    def format_last_seen(self, last_seen_str):
        """Format last seen timestamp"""
        try:
            if not last_seen_str:
                return {"formatted": "Never", "ago": "Never", "is_online": False}
                
            # Handle different timestamp formats
            if 'Z' in last_seen_str:
                last_seen_str = last_seen_str.replace('Z', '+00:00')
            
            utc_time = datetime.fromisoformat(last_seen_str)
            ist = pytz.timezone("Asia/Kolkata")
            ist_time = utc_time.astimezone(ist)
            diff = datetime.now().astimezone(ist) - ist_time
            
            mins = int(diff.total_seconds() // 60)
            if mins < 60:
                ago = f"{mins}m ago"
            else:
                hrs = mins // 60
                if hrs < 24:
                    ago = f"{hrs}h ago"
                else:
                    days = hrs // 24
                    ago = f"{days}d ago"
            
            return {
                "formatted": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
                "ago": ago,
                "is_online": mins < 10
            }
        except Exception as e:
            print(f"Time formatting error: {e}")
            return {"formatted": last_seen_str, "ago": "Unknown", "is_online": False}

# Initialize tracker
tracker = GensynTracker()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/track', methods=['POST'])
def track_node():
    try:
        eoa_address = request.form.get('eoa_address', '').strip()
        
        if not eoa_address:
            return jsonify({"error": "EOA address is required"}), 400
        
        if not Web3.is_address(eoa_address):
            return jsonify({"error": "Invalid EOA address format"}), 400
        
        # Get peer IDs
        peer_ids = tracker.get_peer_ids_from_eoa(eoa_address)
        
        if not peer_ids:
            return jsonify({
                "error": "No active nodes found for this EOA address",
                "eoa": eoa_address,
                "nodes": []
            }), 404
        
        # Fetch node data
        node_data = tracker.fetch_rank_data(peer_ids)
        
        if not node_data:
            return jsonify({
                "error": "Unable to fetch node data from Gensyn API",
                "eoa": eoa_address,
                "nodes": []
            }), 503
        
        nodes_info = []
        ranks = node_data.get('ranks', [])
        stats = node_data.get('stats', {})
        
        for i, rank_info in enumerate(ranks):
            last_seen = tracker.format_last_seen(rank_info.get('lastSeen', ''))
            
            node_info = {
                "node_id": i + 1,
                "peer_id": rank_info.get('peerId', ''),
                "rank": rank_info.get('rank', 'N/A'),
                "total_wins": rank_info.get('totalWins', 0),
                "total_rewards": rank_info.get('totalRewards', 0),
                "last_seen": last_seen,
                "status": "online" if last_seen['is_online'] else "offline"
            }
            nodes_info.append(node_info)
        
        return jsonify({
            "eoa": eoa_address,
            "nodes": nodes_info,
            "stats": {
                "total_nodes": stats.get('totalNodes', 0),
                "ranked_nodes": stats.get('rankedNodes', 0),
                "your_nodes": len(peer_ids)
            },
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        print(f"Server error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "web3_connected": tracker.w3.is_connected() if hasattr(tracker, 'w3') else False
    })

# Vercel requires this
if __name__ == '__main__':
    app.run(debug=True)
else:
    # For Vercel serverless
    def handler(request):
        from flask import Request, Response
        import json
        
        # Convert Vercel request to Flask request
        with app.request_context(request):
            try:
                return app.full_dispatch_request()
            except Exception as e:
                return Response(json.dumps({"error": str(e)}), status=500, mimetype='application/json')
