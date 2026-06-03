"""
Browser-based live map (no X11 window required).
Open http://127.0.0.1:8765/ while the simulation is running.
"""
import argparse
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from geo.sim_control import read_time_scale, write_time_scale, VALID_SCALES
from visualization.mcast_feed import start_feed
from visualization.plot_live import LivePlotState

_SCALE_BUTTONS = ''.join(
    f'<button type="button" class="scale-btn" data-scale="{s}">{s}×</button>'
    for s in VALID_SCALES
)

INDEX_HTML = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Sensors — Eastern Canada live map</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1rem; background: #1a1a2e; color: #eee; }}
    h1 {{ font-size: 1.2rem; margin-bottom: 0.25rem; }}
    .controls {{ margin: 0.75rem 0; display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }}
    .scale-btn {{
      background: #2c3e6b; color: #eee; border: 1px solid #556; padding: 0.35rem 0.65rem;
      border-radius: 4px; cursor: pointer; font-size: 0.9rem;
    }}
    .scale-btn:hover {{ background: #3d5289; }}
    .scale-btn.active {{ background: #c44e00; border-color: #e67e22; }}
    #scale-label {{ margin-left: 0.5rem; color: #ccc; font-size: 0.95rem; }}
    img {{ max-width: 100%; border: 1px solid #444; background: #fff; }}
    .hint {{ color: #aaa; font-size: 0.85rem; margin-top: 0.5rem; }}
  </style>
</head>
<body>
  <h1>Eastern Canada — live sensor fusion</h1>
  <div class="controls">
    <span>Time scale:</span>
    {_SCALE_BUTTONS}
    <span id="scale-label">1×</span>
  </div>
  <p class="hint">Blue = aircraft truth, dots = sensors, ★ = fused. Left: all tracks; right: fused on map. Higher scale = faster flight.</p>
  <img id="frame" alt="live map" src="/live.png">
  <script>
    function setActiveScale(s) {{
      document.querySelectorAll('.scale-btn').forEach(btn => {{
        btn.classList.toggle('active', parseFloat(btn.dataset.scale) === s);
      }});
      document.getElementById('scale-label').textContent = s + '×';
    }}
    async function setScale(s) {{
      await fetch('/scale?value=' + s, {{ method: 'POST' }});
      setActiveScale(s);
    }}
    document.querySelectorAll('.scale-btn').forEach(btn => {{
      btn.addEventListener('click', () => setScale(parseFloat(btn.dataset.scale)));
    }});
    setActiveScale(1);
    function refresh() {{
      document.getElementById('frame').src = '/live.png?t=' + Date.now();
      setTimeout(refresh, 500);
    }}
    refresh();
  </script>
</body>
</html>
"""

_latest_png = b''
_png_lock = threading.Lock()
_state = LivePlotState()
_feed_q = None


def _render_png():
    fig, (ax_map, ax_fused) = plt.subplots(1, 2, figsize=(12, 6))
    try:
        _state.update(_feed_q, ax_map, ax_fused)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=110)
        return buf.getvalue()
    finally:
        plt.close(fig)


def _render_loop(interval):
    global _latest_png
    while True:
        try:
            png = _render_png()
            with _png_lock:
                _latest_png = png
        except Exception as exc:
            print(f"[web_visualizer] render error: {exc}")
        time.sleep(interval)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            body = INDEX_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/live.png'):
            with _png_lock:
                body = _latest_png
            if not body:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/scale':
            qs = parse_qs(parsed.query)
            try:
                value = float(qs.get('value', ['1'])[0])
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            write_time_scale(value)
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


def main():
    global _feed_q
    parser = argparse.ArgumentParser(description='Web visualizer for sensor simulation')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--interval', type=float, default=0.5)
    args = parser.parse_args()

    _feed_q, _ = start_feed()
    threading.Thread(target=_render_loop, args=(args.interval,), daemon=True).start()

    url = f'http://{args.host}:{args.port}/'
    print(f'Web visualizer: open in your browser → {url}')
    print(f'Time scale: {read_time_scale()}× (use buttons in browser)')
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Web visualizer stopped.')


if __name__ == '__main__':
    main()