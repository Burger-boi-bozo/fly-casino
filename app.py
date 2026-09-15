from flask import Flask, jsonify, render_template, request
from simulation import Simulation

app=Flask(__name__)
sim=Simulation()

@app.get('/')
def index():
    return render_template('index.html')

@app.get('/api/state')
def state():
    return jsonify(sim.snapshot())

@app.get('/api/brain/graph')
def brain_graph():
    return jsonify(sim.brain.graph())

@app.get('/api/replay')
def replay():
    return jsonify({'frames':sim.replay_frames(request.args.get('limit',400))})

@app.get('/api/clones')
def clones():
    return jsonify({'clones':sim.list_clones()})

@app.post('/api/control')
def control():
    data=request.get_json(silent=True) or {}
    try:
        return jsonify(sim.control(data.get('action'),data.get('value')))
    except (ValueError,TypeError) as e:
        return jsonify({'error':str(e)}),400

@app.post('/api/intervention')
def intervention():
    data=request.get_json(silent=True) or {}
    try:
        return jsonify(sim.set_intervention(data.get('name'),data.get('value')))
    except (ValueError,TypeError) as e:
        return jsonify({'error':str(e)}),400

@app.post('/api/clone')
def clone():
    data=request.get_json(silent=True) or {}
    return jsonify(sim.clone_current(data.get('label','clone')))

@app.post('/api/clone/activate')
def activate_clone():
    data=request.get_json(silent=True) or {}
    try:
        return jsonify(sim.activate_clone(str(data.get('id',''))))
    except (OSError,ValueError) as e:
        return jsonify({'error':str(e)}),400

@app.post('/api/experiment')
def experiment():
    data=request.get_json(silent=True) or {}
    treatment=data.get('treatment','dopamine_off')
    if treatment not in ('dopamine_off','learning_off','PFL3_off','MBON_off'):
        return jsonify({'error':'unsupported treatment'}),400
    try:
        return jsonify(sim.run_experiment(treatment,data.get('steps',1600)))
    except (ValueError,TypeError) as e:
        return jsonify({'error':str(e)}),400

@app.get('/health')
def health():
    s=sim.snapshot()
    return jsonify(ok=True,version=s['version'],model=s['brain']['model'],ticks=s['ticks'],rounds=s['rounds'],
                   bankroll=s['bankroll'],day=s['day'],running=s['running'])

if __name__=='__main__':
    app.run(host='0.0.0.0',port=8080,threaded=True)
