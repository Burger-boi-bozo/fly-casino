import copy, json, math, os, random, threading, time, uuid
from brain import Brain, fresh_brain
from connectome import CATALOG
from world import WORLD, SITES, SITE_BY_ID, MACHINES, WALLS, angle_wrap, clamp, distance_xy, try_move

STATE_DIR='/var/lib/fly-casino'
COLONY_FILE=os.path.join(STATE_DIR,'colony-v4.json')
LOCK=threading.RLock()

TRAIT_KEYS=('reward_sensitivity','punishment_sensitivity','exploration','social_gain','vision_gain','odor_gain','energy_efficiency')
COLORS=['#7bdff2','#ffd166','#78dc99','#c6a6ff','#ff8ea1','#ffb86b','#72e1d1','#9fb3ff','#ef9cff','#9de36d','#e9c46a','#f4a261']


def atomic_save(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    tmp=path+'.tmp'
    with open(tmp,'w') as f: json.dump(obj,f,separators=(',',':'))
    os.replace(tmp,path)


def founder_traits(seed):
    r=random.Random(seed)
    return {
        'reward_sensitivity':round(r.uniform(.88,1.14),3),'punishment_sensitivity':round(r.uniform(.88,1.14),3),
        'exploration':round(r.uniform(.82,1.18),3),'social_gain':round(r.uniform(.03,.12),3),
        'vision_gain':round(r.uniform(.90,1.10),3),'odor_gain':round(r.uniform(.90,1.12),3),
        'energy_efficiency':round(r.uniform(.90,1.10),3)
    }


def make_fly(index,seed,parent=None,primary=None):
    r=random.Random(seed*1009+index*9176)
    b=fresh_brain(primary.get('brain') if primary else None)
    traits=founder_traits(seed+index)
    if parent:
        traits=copy.deepcopy(parent['traits'])
        for k in TRAIT_KEYS:
            traits[k]=round(clamp(traits[k]+r.gauss(0,.045),.55,1.55),3)
        b=copy.deepcopy(parent['brain'])
        for i in range(3): b['slot_q'][i]+=r.gauss(0,.18)
    b['reward_sensitivity']=traits['reward_sensitivity']; b['punishment_sensitivity']=traits['punishment_sensitivity']
    fid=uuid.uuid4().hex[:8]
    return {
        'id':fid,'name':f"Fly {index+1}",'color':COLORS[index%len(COLORS)],'parent_id':parent['id'] if parent else None,
        'generation':(parent.get('generation',0)+1) if parent else 0,'born':time.time(),'age':0.0,
        'x':110+r.uniform(-35,35),'y':770+r.uniform(-35,35),'heading':r.uniform(-math.pi,math.pi),
        'energy':r.uniform(76,98),'hunger':r.uniform(8,24),'thirst':r.uniform(8,22),'fatigue':r.uniform(4,20),
        'stress':r.uniform(4,18),'curiosity':r.uniform(55,82),'health':100.0,'mood':r.uniform(52,72),
        'goal':'explore','target':None,'waypoint':None,'action':'spawn','indoors':None,'last_action':-99.0,'last_goal':-99.0,
        'bankroll':round((primary.get('bankroll',500) if primary and index==0 else 500.0),2),
        'rounds':int(primary.get('rounds',0) if primary and index==0 else 0),'wins':0,'losses':0,'brain':b,'traits':traits,
        'memory':{'known':{'home':{'x':110,'y':770,'confidence':1.0}},'recent_rewards':[]},
        'retina':[0.0]*24,'social':{'nearest':None,'distance':None,'observations':0,'influence':0.0},
        'sleep':{'episodes':0,'consolidations':0},'stats':{'distance':0.0,'casino_time':0.0,'social_events':0,'food':0,'water':0,'hazards':0}
    }


def fresh_colony(primary=None,count=12,seed=4404):
    count=max(2,min(int(count),40))
    flies=[make_fly(i,seed,primary=primary) for i in range(count)]
    return {
        'version':4,'engine':'v4-colony-connectome','seed':seed,'running':True,'speed':1.0,'ticks':0,'sim_seconds':0.0,
        'day':1,'clock':8.0,'world_seed':seed,'flies':flies,'selected':flies[0]['id'],'events':[],
        'environment':{'machine_p':[m['base_p'] for m in MACHINES],'weather':'clear','epoch':0,'food_stock':100.0},
        'lineage':[],'experiments':[],'created':time.time(),'migration':{'from_v3':bool(primary)}
    }


class Colony:
    def __init__(self,primary_snapshot=None):
        self.rng=random.Random(4404); self.last_save=time.time(); self._stop=False
        try:
            with open(COLONY_FILE) as f: self.state=json.load(f)
            if int(self.state.get('version',0))!=4: raise ValueError('not v4')
        except Exception:
            self.state=fresh_colony(primary_snapshot)
            self.save()
        self.brains={}
        self._rebuild_brains()
        self.thread=threading.Thread(target=self._runner,daemon=True); self.thread.start()

    def _rebuild_brains(self):
        self.brains={f['id']:Brain(f['brain']) for f in self.state['flies']}

    def save(self): atomic_save(COLONY_FILE,self.state)

    def event(self,text,kind='info',fly_id=None):
        self.state['events'].append({'t':round(self.state['sim_seconds'],1),'day':self.state['day'],'clock':round(self.state['clock'],2),'text':text,'kind':kind,'fly_id':fly_id})
        self.state['events']=self.state['events'][-160:]

    def compound_eye(self,fly):
        bins=[0.0]*24; classes=['']*24
        gain=fly['traits']['vision_gain']; fov=math.radians(210); maxd=340*gain
        objects=[]
        for s in SITES:
            d=distance_xy(fly['x'],fly['y'],s['x'],s['y'])
            if d<=maxd+s['r']: objects.append((s['x'],s['y'],s['kind'],d))
        for other in self.state['flies']:
            if other['id']==fly['id']: continue
            d=distance_xy(fly['x'],fly['y'],other['x'],other['y'])
            if d<maxd: objects.append((other['x'],other['y'],'fly',d))
        for x,y,kind,d in objects:
            rel=angle_wrap(math.atan2(y-fly['y'],x-fly['x'])-fly['heading'])
            if abs(rel)>fov/2: continue
            j=int((rel+fov/2)/fov*24); j=max(0,min(23,j)); v=clamp((1-d/maxd)*gain,0,1)
            if v>bins[j]: bins[j]=v; classes[j]=kind
        fly['retina']=[round(v,3) for v in bins]
        return bins,classes

    def odor(self,fly,kind):
        best=0.0; scale={'food':270,'water':220,'casino':170,'home':140,'explore':240}.get(kind,180)
        for s in SITES:
            sk='explore' if s['kind']=='explore' else s['kind']
            if sk!=kind: continue
            d=distance_xy(fly['x'],fly['y'],s['x'],s['y']); best=max(best,math.exp(-d/scale))
        return clamp(best*fly['traits']['odor_gain'],0,1)

    def sensory(self,fly):
        retina,_=self.compound_eye(fly)
        left=max(retina[:8] or [0]); center=max(retina[8:16] or [0]); right=max(retina[16:] or [0])
        return {
            'vision_left':left,'vision_center':center,'vision_right':right,'food_odor':self.odor(fly,'food'),
            'water_odor':self.odor(fly,'water'),'flower_odor':self.odor(fly,'explore'),'casino_cue':self.odor(fly,'casino')*.55,
            'home_cue':self.odor(fly,'home'),'hazard':0.0,'hunger':fly['hunger']/100,'thirst':fly['thirst']/100,
            'fatigue':fly['fatigue']/100,'stress':fly['stress']/100,'novelty':fly['curiosity']/100
        }

    def social_step(self,fly):
        nearest=None; nd=9999
        for other in self.state['flies']:
            if other['id']==fly['id']: continue
            d=distance_xy(fly['x'],fly['y'],other['x'],other['y'])
            if d<nd: nd=d; nearest=other
        fly['social']['nearest']=nearest['id'] if nearest else None; fly['social']['distance']=round(nd,1) if nearest else None
        if nearest and nd<115:
            gain=fly['traits']['social_gain']
            b=fly['brain']; ob=nearest['brain']
            for i in range(3): b['slot_q'][i]+=gain*.008*(ob['slot_q'][i]-b['slot_q'][i])
            for sid,m in nearest['memory']['known'].items():
                if sid not in fly['memory']['known'] and self.rng.random()<gain*.08:
                    fly['memory']['known'][sid]=copy.deepcopy(m); fly['social']['observations']+=1; fly['stats']['social_events']+=1
                    self.event(f"{fly['name']} socially learned about {sid} from {nearest['name']}",'social',fly['id'])
            fly['social']['influence']=round(gain*(1-nd/115),4)
        else: fly['social']['influence']=0.0

    def discover(self,fly):
        for s in SITES:
            d=distance_xy(fly['x'],fly['y'],s['x'],s['y'])
            if d<170:
                fly['memory']['known'][s['id']]={'x':s['x']+self.rng.gauss(0,4),'y':s['y']+self.rng.gauss(0,4),'confidence':1.0}

    def choose_goal(self,fly,mbon):
        if self.state['sim_seconds']-fly['last_goal']<3.0: return
        scores={
            'food':fly['hunger']*.11 + max(0,mbon.get('appetitive',0))*.25,
            'water':fly['thirst']*.12,'home':fly['fatigue']*.12+max(0,fly['stress']-55)*.06,
            'explore':fly['curiosity']*.065*fly['traits']['exploration']+max(0,mbon.get('novelty',0))*.3,
            'casino':max(0,58-fly['stress'])*.021+mbon.get('gambling',0)*.45+max(fly['brain']['slot_q'])*.10
        }
        if fly['bankroll']<4: scores['casino']-=5
        keys=list(scores); vals=[scores[k] for k in keys]; m=max(vals); ex=[math.exp((v-m)/1.15) for v in vals]
        r=self.rng.random()*sum(ex); a=0; goal=keys[-1]
        for k,p in zip(keys,ex):
            a+=p
            if r<=a: goal=k; break
        fly['goal']=goal; fly['last_goal']=self.state['sim_seconds']; target=None
        known=fly['memory']['known']
        if goal in ('food','water','home') and goal in known: target=goal
        elif goal=='explore' and 'garden' in known and self.rng.random()<.45: target='garden'
        elif goal=='casino':
            ids=[x for x in ('cherry','lemon','diamond') if x in known]
            if ids:
                arms=[SITE_BY_ID[x]['machine'] for x in ids]; arm=self.brains[fly['id']].choose_machine(arms,self.rng); target=('cherry','lemon','diamond')[arm]
        fly['target']=target
        if target is None:
            ang=fly['heading']+self.rng.uniform(-1.5,1.5); d=self.rng.uniform(120,360)
            fly['waypoint']={'x':clamp(fly['x']+math.cos(ang)*d,20,WORLD['width']-20),'y':clamp(fly['y']+math.sin(ang)*d,20,WORLD['height']-20)}
        else: fly['waypoint']=None

    def target_xy(self,fly):
        if fly.get('target') and fly['target'] in fly['memory']['known']:
            m=fly['memory']['known'][fly['target']]; return m['x'],m['y']
        if fly.get('waypoint'): return fly['waypoint']['x'],fly['waypoint']['y']
        return None

    def interact(self,fly,site,brain):
        if self.state['sim_seconds']-fly['last_action']<2.2: return
        fly['last_action']=self.state['sim_seconds']; fly['memory']['known'][site['id']]={'x':site['x'],'y':site['y'],'confidence':1.0}
        if site['kind']=='food':
            before=fly['hunger']; fly['hunger']=clamp(fly['hunger']-58,0,100); fly['energy']=clamp(fly['energy']+26,0,100); fly['stats']['food']+=1
            brain.learn((before-fly['hunger'])/15,.2,'general'); fly['action']='feed'
        elif site['kind']=='water':
            before=fly['thirst']; fly['thirst']=clamp(fly['thirst']-70,0,100); fly['stats']['water']+=1; brain.learn((before-fly['thirst'])/16,.15,'general'); fly['action']='drink'
        elif site['kind']=='home':
            before=fly['fatigue']; fly['fatigue']=clamp(fly['fatigue']-72,0,100); fly['energy']=clamp(fly['energy']+45,0,100); fly['stress']=clamp(fly['stress']-24,0,100)
            fly['sleep']['episodes']+=1; self.consolidate(fly); brain.learn((before-fly['fatigue'])/14,.12,'general'); fly['action']='sleep'
        elif site['kind']=='explore':
            fly['curiosity']=clamp(fly['curiosity']-44,0,100); brain.learn(.6,.85,'general'); fly['action']='inspect'
        elif site['kind']=='casino': self.gamble(fly,site['machine'],brain); return
        fly['target']=None; fly['waypoint']=None

    def consolidate(self,fly):
        rewards=fly['memory']['recent_rewards'][-16:]
        if rewards:
            avg=sum(x['reward'] for x in rewards)/len(rewards)
            arm=max(range(3),key=lambda i:sum(x['reward'] for x in rewards if x['arm']==i) if any(x['arm']==i for x in rewards) else -999)
            fly['brain']['slot_q'][arm]+=clamp(avg*.006,-.12,.12)
        for m in fly['memory']['known'].values(): m['confidence']=min(1.0,m.get('confidence',.7)+.04)
        fly['sleep']['consolidations']+=1

    def gamble(self,fly,arm,brain):
        if fly['bankroll']<=0: fly['target']=None; return
        base=1 if fly['bankroll']<150 else 2 if fly['bankroll']<500 else 5
        q=fly['brain']['slot_q'][arm]; risk=MACHINES[arm]['risk']; wager=max(1,round(base*clamp(1+risk*clamp((q+5)/18,0,1)-fly['stress']/130,.5,2.2)))
        wager=min(wager,max(1,int(fly['bankroll']))); win=self.rng.random()<self.state['environment']['machine_p'][arm]
        reward=round(wager*MACHINES[arm]['multiplier'],2) if win else -float(wager)
        brain.update_machine(arm,reward); brain.learn(reward,.08,'casino'); fly['bankroll']=round(max(0,fly['bankroll']+reward),2); fly['rounds']+=1
        fly['wins']+=int(win); fly['losses']+=int(not win); fly['stress']=clamp(fly['stress']+(-2 if win else 2+2*risk),0,100); fly['mood']=clamp(fly['mood']+(4 if win else -3),0,100)
        fly['memory']['recent_rewards'].append({'arm':arm,'reward':reward}); fly['memory']['recent_rewards']=fly['memory']['recent_rewards'][-40:]
        fly['action']='gamble'; self.event(f"{fly['name']} wagered F฿{wager} at {MACHINES[arm]['name']}: {reward:+.1f}",'win' if win else 'loss',fly['id'])
        stay=.45+clamp(q/22,-.2,.28)-fly['stress']/190
        if self.rng.random()>clamp(stay,.05,.9): fly['target']=None; fly['waypoint']=None

    def fly_tick(self,fly,dt):
        brain=self.brains[fly['id']]; fly['age']+=dt
        self.discover(fly); self.social_step(fly)
        sensory=self.sensory(fly); kc=brain.encode(sensory); mbon=brain.mushroom_body(kc); self.choose_goal(fly,mbon)
        target=self.target_xy(fly)
        if target is None: return
        tx,ty=target; d=distance_xy(fly['x'],fly['y'],tx,ty); bearing=math.atan2(ty-fly['y'],tx-fly['x'])
        turn,lm,rm=brain.navigation(fly['heading'],bearing,None); fly['heading']=angle_wrap(fly['heading']+turn*2.1*dt+self.rng.uniform(-.025,.025))
        forward=clamp((lm+rm)/.7,0,1.2); speed=(34+fly['energy']*.38)*forward
        old=(fly['x'],fly['y']); try_move(fly,math.cos(fly['heading'])*speed*dt,math.sin(fly['heading'])*speed*dt)
        fly['stats']['distance']+=distance_xy(old[0],old[1],fly['x'],fly['y']); fly['action']='move'
        eff=fly['traits']['energy_efficiency']; fly['energy']=clamp(fly['energy']-.036*dt/eff,0,100); fly['hunger']=clamp(fly['hunger']+.022*dt/eff,0,100); fly['thirst']=clamp(fly['thirst']+.027*dt/eff,0,100); fly['fatigue']=clamp(fly['fatigue']+.016*dt/eff,0,100); fly['curiosity']=clamp(fly['curiosity']+.009*dt,0,100)
        if fly['hunger']>94 or fly['thirst']>94: fly['health']=clamp(fly['health']-.05*dt,0,100)
        elif fly['health']<100: fly['health']=clamp(fly['health']+.01*dt,0,100)
        if fly['health']<=0:
            fly.update({'x':110,'y':770,'health':55,'hunger':65,'thirst':65,'fatigue':50,'stress':78,'target':None,'waypoint':None}); brain.learn(-12,.1,'general')
        if d<44:
            if fly.get('target') in SITE_BY_ID: self.interact(fly,SITE_BY_ID[fly['target']],brain)
            else: fly['target']=None; fly['waypoint']=None

    def tick(self,dt):
        s=self.state; dt=min(dt,1.2); s['ticks']+=1; s['sim_seconds']+=dt; s['clock']+=dt/60
        if s['clock']>=24: s['clock']-=24; s['day']+=1
        if s['ticks']%2200==0:
            s['environment']['epoch']+=1; s['environment']['machine_p']=[clamp(m['base_p']+self.rng.uniform(-.09,.09),.03,.78) for m in MACHINES]; s['environment']['weather']=self.rng.choice(['clear','clear','wind','mist','rain','heat']); self.event('World schedule/weather shifted','world')
        for fly in list(s['flies']): self.fly_tick(fly,dt)
        if time.time()-self.last_save>4: self.save(); self.last_save=time.time()

    def _runner(self):
        last=time.time()
        while not self._stop:
            time.sleep(.06); now=time.time(); real=min(.2,now-last); last=now
            with LOCK:
                if self.state.get('running',True): self.tick(real*float(self.state.get('speed',1.0)))

    def selected(self):
        sid=self.state.get('selected'); return next((f for f in self.state['flies'] if f['id']==sid),self.state['flies'][0])

    def public_fly(self,fly,detail=False):
        out={k:copy.deepcopy(v) for k,v in fly.items() if k!='brain'}
        b=fly['brain']; out['brain']={'model':b['model'],'slot_q':[round(x,3) for x in b['slot_q']],'slot_counts':b['slot_counts'],'activity':copy.deepcopy(b['activity']),'learning_events':b['learning_events']}
        if detail:
            ids={k:[CATALOG.cell(k,i) for i in range(min(8,len(CATALOG.circuits.get(k,[]))))] for k in ('KC','MBON','PAM','PPL1','EPG','PFL3','DNa02')}
            out['connectome_ids']=ids
        return out

    def snapshot(self):
        with LOCK:
            flies=[self.public_fly(f,detail=(f['id']==self.state.get('selected'))) for f in self.state['flies']]
            s={k:copy.deepcopy(v) for k,v in self.state.items() if k!='flies'}
        s['flies']=flies; s['world']=WORLD; s['sites']=SITES; s['walls']=WALLS; s['connectome']=CATALOG.summary(); return s

    def select(self,fid):
        if not any(f['id']==fid for f in self.state['flies']): raise ValueError('unknown fly')
        self.state['selected']=fid; return self.snapshot()

    def breed(self,parent_id=None):
        if len(self.state['flies'])>=40: raise ValueError('colony limit 40')
        parent=next((f for f in self.state['flies'] if f['id']==parent_id),self.selected())
        child=make_fly(len(self.state['flies']),self.state['seed']+self.state['ticks'],parent=parent)
        child['name']=parent['name']+' · child'; self.state['flies'].append(child); self.brains[child['id']]=Brain(child['brain'])
        self.state['lineage'].append({'parent':parent['id'],'child':child['id'],'generation':child['generation'],'traits':copy.deepcopy(child['traits'])}); self.event(f"{child['name']} born from {parent['name']}",'lineage',child['id']); self.save(); return self.public_fly(child,True)

    def mutate(self,fid,trait,delta):
        fly=next((f for f in self.state['flies'] if f['id']==fid),None)
        if not fly or trait not in TRAIT_KEYS: raise ValueError('invalid fly/trait')
        fly['traits'][trait]=round(clamp(float(fly['traits'][trait])+float(delta),.35,1.8),3)
        if trait in ('reward_sensitivity','punishment_sensitivity'): fly['brain'][trait]=fly['traits'][trait]
        self.event(f"Persistent mutation: {fly['name']} {trait} → {fly['traits'][trait]}",'mutation',fid); self.save(); return self.public_fly(fly,True)

    def control(self,action,value=None):
        if action=='start': self.state['running']=True
        elif action=='pause': self.state['running']=False
        elif action=='speed': self.state['speed']=clamp(float(value),.25,80)
        elif action=='select': return self.select(str(value))
        elif action=='world_event': self.state['ticks']=max(self.state['ticks'],2199); self.state['environment']['machine_p']=[clamp(m['base_p']+self.rng.uniform(-.12,.12),.03,.78) for m in MACHINES]; self.event('Researcher forced environment shift','world')
        else: raise ValueError('unknown action')
        self.save(); return self.snapshot()

    def run_batch(self,population=24,steps=2500,treatment='control',seed=8801):
        population=max(4,min(int(population),120)); steps=max(200,min(int(steps),12000)); r=random.Random(seed)
        groups=[]
        for condition in ('control',treatment) if treatment!='control' else ('control',):
            outcomes=[]
            for n in range(population):
                cash=500.0; q=[0.0,0.0,0.0]; stress=10.0; bets=0; wins=0; social=0.08
                if condition=='dopamine_off': alpha=0.0
                else: alpha=.055
                if condition=='high_social': social=.22
                if condition=='sleep_deprived': stress=35
                for t in range(steps):
                    if r.random()<.018*(1+social):
                        arm=max(range(3),key=lambda i:q[i]+r.gauss(0,2.2)); wager=1 if cash<150 else 2 if cash<500 else 5
                        p=self.state['environment']['machine_p'][arm]; reward=wager*MACHINES[arm]['multiplier'] if r.random()<p else -wager
                        q[arm]+=alpha*(reward-q[arm]); cash=max(0,cash+reward); bets+=1; wins+=int(reward>0); stress=clamp(stress+(-.4 if reward>0 else .7),0,100)
                    if condition=='sleep_deprived': stress=clamp(stress+.002,0,100)
                outcomes.append({'cash':cash,'bets':bets,'wins':wins,'stress':stress,'q':q})
            groups.append({'condition':condition,'n':population,'mean_bankroll':round(sum(x['cash'] for x in outcomes)/population,2),'mean_bets':round(sum(x['bets'] for x in outcomes)/population,2),'mean_stress':round(sum(x['stress'] for x in outcomes)/population,2),'win_rate':round(sum(x['wins'] for x in outcomes)/max(1,sum(x['bets'] for x in outcomes)),4)})
        rec={'id':uuid.uuid4().hex[:8],'population':population,'steps':steps,'treatment':treatment,'seed':seed,'groups':groups,'created':time.time()}; self.state['experiments'].append(rec); self.state['experiments']=self.state['experiments'][-30:]; self.save(); return rec
