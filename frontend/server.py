#!/usr/bin/env python3
"""Minimal server for the trading dashboard."""
import http.server
import json
import csv
import os

PORT = 8080
TRADES_CSV = os.path.join(os.path.dirname(__file__), '..', 'trades_current.csv')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def do_GET(self):
        if self.path == '/api/trades':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            trades = []
            with open(TRADES_CSV) as f:
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
            self.wfile.write(json.dumps(trades).encode())
            return
        return super().do_GET()


if __name__ == '__main__':
    print(f"Dashboard running at http://localhost:{PORT}")
    server = http.server.HTTPServer(('', PORT), Handler)
    server.serve_forever()
