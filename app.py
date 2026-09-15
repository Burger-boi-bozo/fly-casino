from flask import Flask, jsonify, render_template, request
from simulation import Simulation

app=Flask(__name__)
sim=Simulation()

@app.get('/')
def index(): return render_template('index.html')

@app.get('/api/state')
def state(): return jsonify(sim.snapshot())

@app.post('/api/control')
def control():
    data=request.get_json(silent=True) or {}
    try: return jsonify(sim.control(data.get('action'),data.get('value')))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.get('/health')
def health():
    s=sim.snapshot()
    return jsonify(ok=True,version=s['version'],ticks=s['ticks'],rounds=s['rounds'],bankroll=s['bankroll'])

if __name__=='__main__': app.run(host='0.0.0.0',port=8080,threaded=True)
