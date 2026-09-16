from flask import Flask, jsonify, render_template, request
from simulation import Simulation
from colony import Colony
from connectome import CATALOG

app=Flask(__name__)
primary=Simulation()
colony=Colony(primary.snapshot())

@app.get('/')
def index(): return render_template('index.html')

@app.get('/api/state')
def state():
    return jsonify({'version':4,'primary':primary.snapshot(),'colony':colony.snapshot(),'connectome':CATALOG.summary()})

@app.get('/api/v3/state')
def v3_state(): return jsonify(primary.snapshot())

@app.get('/api/v4/colony')
def v4_colony(): return jsonify(colony.snapshot())

@app.get('/api/v4/connectome')
def connectome_summary(): return jsonify(CATALOG.summary())

@app.get('/api/v4/connectome/cells')
def connectome_cells():
    circuit=request.args.get('circuit','KC'); limit=request.args.get('limit',50)
    return jsonify({'circuit':circuit,'cells':CATALOG.cells(circuit,limit)})

@app.post('/api/v4/control')
def v4_control():
    d=request.get_json(silent=True) or {}
    try: return jsonify(colony.control(d.get('action'),d.get('value')))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/v4/breed')
def v4_breed():
    d=request.get_json(silent=True) or {}
    try: return jsonify(colony.breed(d.get('parent_id')))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/v4/mutate')
def v4_mutate():
    d=request.get_json(silent=True) or {}
    try: return jsonify(colony.mutate(d.get('fly_id'),d.get('trait'),d.get('delta',0)))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/v4/batch')
def v4_batch():
    d=request.get_json(silent=True) or {}
    try: return jsonify(colony.run_batch(d.get('population',24),d.get('steps',2500),d.get('treatment','control'),d.get('seed',8801)))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

# V3 compatibility/research endpoints remain available for the founding organism.
@app.get('/api/brain/graph')
def brain_graph(): return jsonify(primary.brain.graph())

@app.get('/api/replay')
def replay(): return jsonify({'frames':primary.replay_frames(request.args.get('limit',400))})

@app.get('/api/clones')
def clones(): return jsonify({'clones':primary.list_clones()})

@app.post('/api/control')
def control():
    d=request.get_json(silent=True) or {}
    try: return jsonify(primary.control(d.get('action'),d.get('value')))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/intervention')
def intervention():
    d=request.get_json(silent=True) or {}
    try: return jsonify(primary.set_intervention(d.get('name'),d.get('value')))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/clone')
def clone():
    d=request.get_json(silent=True) or {}; return jsonify(primary.clone_current(d.get('label','clone')))

@app.post('/api/clone/activate')
def activate_clone():
    d=request.get_json(silent=True) or {}
    try: return jsonify(primary.activate_clone(str(d.get('id',''))))
    except (OSError,ValueError) as e: return jsonify({'error':str(e)}),400

@app.post('/api/experiment')
def experiment():
    d=request.get_json(silent=True) or {}; treatment=d.get('treatment','dopamine_off')
    if treatment not in ('dopamine_off','learning_off','PFL3_off','MBON_off'): return jsonify({'error':'unsupported treatment'}),400
    try: return jsonify(primary.run_experiment(treatment,d.get('steps',1600)))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400

@app.get('/health')
def health():
    p=primary.snapshot(); c=colony.snapshot()
    return jsonify(ok=True,version=4,release='v4.0.0',primary_model=p['brain']['model'],primary_bankroll=p['bankroll'],
                   primary_rounds=p['rounds'],colony_engine=c['engine'],flies=len(c['flies']),day=c['day'],running=c['running'],
                   connectome_dataset=CATALOG.summary()['dataset'])

if __name__=='__main__': app.run(host='0.0.0.0',port=8080,threaded=True)
