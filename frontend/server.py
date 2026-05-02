#!/usr/bin/env python3
"""Dashboard server with both raw and optimized trade data."""
import http.server
import json
import csv
import os
from datetime import datetime

PORT = 8080
BASE = os.path.join(os.path.dirname(__file__), '..')
RAW_CSV = os.path.join(BASE, 'trades_current.csv')
OPT_CSV = os.path.join(BASE, 'trades_optimized.csv')


def load_trades(path):
    trades = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append({
                'entry_time': row['entry_time'],
                'exit_time': row['exit_time'],
                'direction': row['direction'],
                'model': row['model'],
                'tag': row['tag'],
                'entry': float(row['entry']),
                'exit': float(row['exit']),
                'stop': float(row['stop']),
                'target': float(row['target']),
                'reason': row['reason'],
                'risk_ticks': float(row['risk_ticks']),
                'total_r': float(row['total_r']),
            })
    return trades


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def do_GET(self):
        if self.path == '/api/trades':
            self._json_response(load_trades(OPT_CSV if os.path.exists(OPT_CSV) else RAW_CSV))
            return
        if self.path == '/api/trades/raw':
            self._json_response(load_trades(RAW_CSV))
            return
        return super().do_GET()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


if __name__ == '__main__':
    print(f"Dashboard running at http://localhost:{PORT}")
    server = http.server.HTTPServer(('', PORT), Handler)
    server.serve_forever()
