import json, math, os, random, threading, time

STATE_DIR = '/var/lib/fly-casino'
STATE_FILE = os.path.join(STATE_DIR, 'state.json')
WORLD = {'width': 1200, 'height': 760}
SITES = [
    {'id':'home','name':'Nest','kind':'home','x':105,'y':650,'r':54},
    {'id':'food','name':'Fruit Stand','kind':'food','x':245,'y':185,'r':50},
    {'id':'water','name':'Water Drop','kind':'water','x':610,'y':105,'r':45},
    {'id':'cherry','name':'Cherry Casino','kind':'casino','machine':0,'x':930,'y':190,'r':62},
    {'id':'lemon','name':'Lemon Casino','kind':'casino','machine':1,'x':1060,'y':390,'r':62},
    {'id':'diamond','name':'Diamond Casino','kind':'casino','machine':2,'x':850,'y':615,'r':62},
    {'id':'garden','name':'Flower Garden','kind':'explore','x':475,'y':420,'r':70},
]
MACHINES = [
    {'name':'Cherry','icon':'🍒','base_p':0.62,'win':6,'loss':-4,'risk':0.2},
    {'name':'Lemon','icon':'🍋','base_p':0.38,'win':14,'loss':-6,'risk':0.55},
    {'name':'Diamond','icon':'💎','base_p':0.09,'win':75,'loss':-8,'risk':1.0},
]
LOCK = threading.RLock()

def clamp(v,a,b): return max(a,min(b,v))
def dist(a,b): return math.hypot(a['x']-b['x'], a['y']-b['y'])

def fresh_state():
    return {
        'version':2,'running':True,'speed':1.0,'ticks':0,'sim_seconds':0.0,'day':1,'clock':8.0,
        'bankroll':1000.0,'rounds':0,'wins_total':0,'losses_total':0,
        'fly':{'x':120.0,'y':630.0,'heading':-0.7,'energy':92.0,'hunger':15.0,'thirst':10.0,
               'fatigue':8.0,'stress':10.0,'curiosity':62.0,'mood':65.0,'goal':'explore','target':'garden','last_action_sim':-99.0},
        'brain':{'slot_q':[0.0,0.0,0.0],'slot_counts':[0,0,0],'slot_wins':[0,0,0],
                 'goal_q':{'casino':0.0,'food':0.0,'water':0.0,'home':0.0,'explore':0.0},
                 'alpha':0.075,'gamma':0.90,'temperature':2.8,'epsilon':0.09,'dopamine':0.0,
                 'prediction_error':0.0,'sensory':{},'mbon':{},'dan':0.0,'kc_activity':0.0},
        'environment':{'machine_p':[m['base_p'] for m in MACHINES],'drift_epoch':0,'event':'Quiet morning'},
        'history':[],'events':[],'visits':{s['id']:0 for s in SITES},'started_at':time.time(),
    }

def migrate(old):
    if old.get('version') == 2: return old
    s = fresh_state()
    s['bankroll'] = float(old.get('bankroll',1000.0)); s['rounds'] = int(old.get('rounds',0))
    s['brain']['slot_q'] = list(old.get('values',[0,0,0]))[:3]
    s['brain']['slot_counts'] = list(old.get('counts',[0,0,0]))[:3]
    s['brain']['slot_wins'] = list(old.get('wins',[0,0,0]))[:3]
    s['wins_total'] = sum(s['brain']['slot_wins'])
    s['losses_total'] = max(0,s['rounds']-s['wins_total'])
    for h in old.get('history',[])[-60:]:
        s['history'].append({'type':'gamble','round':h.get('round',0),'machine':h.get('arm',0),
                             'reward':h.get('reward',0),'bankroll':h.get('bankroll',s['bankroll']),
                             'pe':h.get('pe',0),'time':s['clock']})
    s['events']=[{'text':'v1 memory migrated into v2 world','kind':'system','tick':0}]
    return s

def load_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(STATE_FILE) as f: return migrate(json.load(f))
    except Exception:
        return fresh_state()

def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp=STATE_FILE+'.tmp'
    with open(tmp,'w') as f: json.dump(s,f,separators=(',',':'))
    os.replace(tmp,STATE_FILE)

def softmax_pick(values,temp,epsilon=0.0):
    if random.random() < epsilon: return random.randrange(len(values))
    t=max(0.18,temp); z=[v/t for v in values]; m=max(z); e=[math.exp(v-m) for v in z]
    r=random.random()*sum(e); a=0
    for i,p in enumerate(e):
        a+=p
        if r<=a: return i
    return len(values)-1

class Simulation:
    def __init__(self):
        self.state=load_state(); self.last_save=time.time(); self._stop=False
        self.thread=threading.Thread(target=self._runner,daemon=True); self.thread.start()
    def event(self,text,kind='info'):
        s=self.state; s['events'].append({'text':text,'kind':kind,'tick':s['ticks']})
        s['events']=s['events'][-35:]
    def choose_goal(self):
        s=self.state; f=s['fly']; b=s['brain']
        drives={
            'food':f['hunger']*0.105 + b['goal_q']['food'],
            'water':f['thirst']*0.12 + b['goal_q']['water'],
            'home':f['fatigue']*0.115 + max(0,f['stress']-50)*0.05 + b['goal_q']['home'],
            'explore':f['curiosity']*0.055 + b['goal_q']['explore'],
            'casino':max(0,55-f['stress'])*0.025 + max(b['slot_q'])*0.20 + b['goal_q']['casino'],
        }
        if s['bankroll'] < 15: drives['casino'] -= 3.5
        if f['energy'] < 18: drives['home'] += 4
        keys=list(drives); vals=[drives[k] for k in keys]
        i=softmax_pick(vals,1.25,0.04); goal=keys[i]
        if goal=='casino':
            mi=softmax_pick(b['slot_q'],b['temperature'],b['epsilon']); target=['cherry','lemon','diamond'][mi]
        elif goal=='explore': target='garden'
        else: target=goal
        f['goal']=goal; f['target']=target
        b['mbon']={k:round(v,3) for k,v in drives.items()}
    def move(self,dt):
        s=self.state; f=s['fly']; target=next(x for x in SITES if x['id']==f['target'])
        dx=target['x']-f['x']; dy=target['y']-f['y']; d=max(0.001,math.hypot(dx,dy))
        desired=math.atan2(dy,dx); delta=(desired-f['heading']+math.pi)%(2*math.pi)-math.pi
        f['heading'] += clamp(delta,-1.8*dt,1.8*dt) + random.uniform(-0.08,0.08)
        speed=(48+0.4*f['energy'])*(0.65 if f['fatigue']>75 else 1.0)
        step=min(d,speed*dt); f['x']+=math.cos(f['heading'])*step; f['y']+=math.sin(f['heading'])*step
        f['x']=clamp(f['x'],15,WORLD['width']-15); f['y']=clamp(f['y'],15,WORLD['height']-15)
        f['energy']=clamp(f['energy']-0.055*dt*10,0,100); f['hunger']=clamp(f['hunger']+0.045*dt*10,0,100)
        f['thirst']=clamp(f['thirst']+0.055*dt*10,0,100); f['fatigue']=clamp(f['fatigue']+0.028*dt*10,0,100)
        if d <= target['r']+8: self.arrive(target)
    def arrive(self,site):
        s=self.state; f=s['fly']; b=s['brain']
        if s['sim_seconds']-f.get('last_action_sim',-99)<2.5: return
        f['last_action_sim']=s['sim_seconds']; s['visits'][site['id']]+=1
        if site['kind']=='food':
            before=f['hunger']; f['hunger']=clamp(f['hunger']-58,0,100); f['energy']=clamp(f['energy']+28,0,100); f['mood']=clamp(f['mood']+6,0,100)
            reward=(before-f['hunger'])/18; b['goal_q']['food']+=0.08*(reward-b['goal_q']['food']); self.event('Ate fruit and restored energy','food')
        elif site['kind']=='water':
            before=f['thirst']; f['thirst']=clamp(f['thirst']-72,0,100); reward=(before-f['thirst'])/20; b['goal_q']['water']+=0.08*(reward-b['goal_q']['water']); self.event('Drank from the water drop','water')
        elif site['kind']=='home':
            before=f['fatigue']; f['fatigue']=clamp(f['fatigue']-68,0,100); f['energy']=clamp(f['energy']+42,0,100); f['stress']=clamp(f['stress']-24,0,100)
            reward=(before-f['fatigue'])/20; b['goal_q']['home']+=0.08*(reward-b['goal_q']['home']); self.event('Rested at the nest','home')
        elif site['kind']=='explore':
            f['curiosity']=clamp(f['curiosity']-42,0,100); f['mood']=clamp(f['mood']+4,0,100); b['goal_q']['explore']+=0.06*(1.5-b['goal_q']['explore']); self.event('Explored the flower garden','explore')
        elif site['kind']=='casino': self.gamble(site['machine'])
        f['curiosity']=clamp(f['curiosity']+random.uniform(2,7),0,100)
        self.choose_goal()
    def gamble(self,arm):
        s=self.state; f=s['fly']; b=s['brain']; m=MACHINES[arm]; p=s['environment']['machine_p'][arm]
        predicted=b['slot_q'][arm]; reward=m['win'] if random.random()<p else m['loss']; pe=reward-predicted
        b['slot_q'][arm]+=b['alpha']*pe; b['slot_counts'][arm]+=1; s['rounds']+=1; s['bankroll']+=reward
        if reward>0: b['slot_wins'][arm]+=1; s['wins_total']+=1; f['mood']=clamp(f['mood']+8,0,100); f['stress']=clamp(f['stress']-3,0,100)
        else: s['losses_total']+=1; f['mood']=clamp(f['mood']-5,0,100); f['stress']=clamp(f['stress']+6+2*m['risk'],0,100)
        b['prediction_error']=pe; b['dopamine']=clamp(pe/25,-1,1); b['dan']=b['dopamine']; b['kc_activity']=random.uniform(.25,.95)
        risk_bonus=(reward/20)-m['risk']*(f['stress']/100); b['goal_q']['casino']+=0.055*(risk_bonus-b['goal_q']['casino'])
        s['history'].append({'type':'gamble','round':s['rounds'],'machine':arm,'reward':reward,'bankroll':round(s['bankroll'],2),'pe':round(pe,3),'time':round(s['clock'],2)})
        s['history']=s['history'][-180:]
        self.event(f"{m['name']} paid {reward:+.0f} FlyBucks",'win' if reward>0 else 'loss')
        if s['bankroll']<=0: s['bankroll']=0; b['goal_q']['casino']-=6; self.event('Bankroll hit zero; gambling drive suppressed','loss')
    def drift_environment(self):
        s=self.state; e=s['environment']; e['drift_epoch']+=1
        new=[]
        for i,m in enumerate(MACHINES): new.append(clamp(m['base_p']+random.uniform(-.11,.11),.025,.82))
        e['machine_p']=new; e['event']=random.choice(['Casino odds shifted','A warm breeze crosses the garden','The room lights dim','Food smells stronger'])
        self.event(e['event'],'world')
    def tick(self,dt):
        s=self.state; f=s['fly']; s['ticks']+=1; s['sim_seconds']+=dt; s['clock']+=dt/45
        if s['clock']>=24: s['clock']-=24; s['day']+=1
        if s['ticks']%850==0: self.drift_environment()
        f['curiosity']=clamp(f['curiosity']+0.015*dt*10,0,100)
        night = s['clock']<6 or s['clock']>22
        if night: f['fatigue']=clamp(f['fatigue']+0.04*dt*10,0,100)
        b=s['brain']; b['dopamine']*=0.92; b['dan']=b['dopamine']; b['kc_activity']*=0.94
        b['sensory']={'food_odor':round(f['hunger']/100,3),'water_need':round(f['thirst']/100,3),'fatigue':round(f['fatigue']/100,3),
                      'casino_cue':round(clamp((max(b['slot_q'])+10)/30,0,1),3),'novelty':round(f['curiosity']/100,3),'stress':round(f['stress']/100,3)}
        if s['ticks']%80==1 or not f.get('target'): self.choose_goal()
        self.move(dt)
        if time.time()-self.last_save>3: save_state(s); self.last_save=time.time()
    def _runner(self):
        last=time.time()
        while not self._stop:
            time.sleep(.05); now=time.time(); real_dt=min(.2,now-last); last=now
            with LOCK:
                if self.state.get('running',True): self.tick(real_dt*self.state.get('speed',1.0))
    def snapshot(self):
        with LOCK:
            s=json.loads(json.dumps(self.state))
        s['world']=WORLD; s['sites']=SITES; s['machines']=[]
        for i,m in enumerate(MACHINES):
            count=s['brain']['slot_counts'][i]; wins=s['brain']['slot_wins'][i]
            s['machines'].append({**m,'q':round(s['brain']['slot_q'][i],3),'count':count,'wins':wins,'win_rate':round(100*wins/max(1,count),1),'current_p':round(100*s['environment']['machine_p'][i],1)})
        s['favorite']=max(range(3),key=lambda i:s['brain']['slot_q'][i])
        return s
    def control(self,action,value=None):
        with LOCK:
            if action=='start': self.state['running']=True
            elif action=='pause': self.state['running']=False
            elif action=='speed': self.state['speed']=clamp(float(value),0.25,20)
            elif action=='reset':
                old=self.state; self.state=fresh_state(); self.state['running']=False; self.event('Fresh v2 brain created','system')
            elif action=='world_reset':
                self.state['fly'].update({'x':120,'y':630,'energy':92,'hunger':15,'thirst':10,'fatigue':8,'stress':10,'curiosity':62,'mood':65}); self.choose_goal(); self.event('Fly returned to nest; learned values preserved','system')
            elif action=='drift': self.drift_environment()
            else: raise ValueError('unknown action')
            save_state(self.state)
            return self.snapshot()
