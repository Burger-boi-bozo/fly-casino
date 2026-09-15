import copy, json, math, os, random, threading, time, uuid
from collections import Counter, deque
from brain import Brain, fresh_brain
from world import (WORLD, SITES, SITE_BY_ID, MACHINES, WALLS, HAZARDS, angle_wrap, clamp,
                   distance_xy, hazard_percepts, light_level, odor_field, try_move,
                   update_hazards, visible_sites)

STATE_DIR='/var/lib/fly-casino'
STATE_FILE=os.path.join(STATE_DIR,'state.json')
CLONE_DIR=os.path.join(STATE_DIR,'clones')
LOCK=threading.RLock()


def fresh_state():
    return {
        'version':3,'running':True,'speed':1.0,'ticks':0,'sim_seconds':0.0,'day':1,'clock':8.0,
        'bankroll':1000.0,'rounds':0,'wins_total':0,'losses_total':0,
        'fly':{'x':120.0,'y':770.0,'heading':-0.65,'energy':92.0,'hunger':14.0,'thirst':10.0,
               'fatigue':8.0,'stress':9.0,'curiosity':68.0,'mood':64.0,'health':100.0,
               'goal':'explore','target':None,'action':'orient','waypoint':None,'indoors':None,
               'last_action_sim':-99.0,'last_goal_sim':-99.0,'last_bet_reward':None,'casino_streak':0},
        'brain':fresh_brain(),
        'memory':{'known':{'home':{'x':110,'y':770,'confidence':1.0,'seen':0}},'episodes':[]},
        'environment':{'machine_p':[m['base_p'] for m in MACHINES],'drift_epoch':0,'weather':'clear',
                       'event':'V3 world online','hazards':copy.deepcopy(HAZARDS),'food_stock':100.0,'water_stock':100.0},
        'research':{'heatmap':[0]*504,'actions':{},'distance':0.0,'casino_seconds':0.0,'explore_seconds':0.0,
                    'bets_after_loss':0,'loss_opportunities':0,'wagers':[],'dopamine':[],'goal_counts':{},
                    'interventions_log':[],'experiments':[]},
        'history':[],'events':[],'visits':{s['id']:0 for s in SITES},'replay_tail':[],
        'started_at':time.time(),'migration':{'from':None},
    }


def migrate(old):
    if int(old.get('version',0))==3:
        # Forward-fill newer fields without discarding persistent learning.
        base=fresh_state()
        for key in ('research','memory','environment','fly'):
            if key not in old: old[key]=base[key]
        for k,v in base['research'].items(): old['research'].setdefault(k,v)
        for k,v in base['fly'].items(): old['fly'].setdefault(k,v)
        for k,v in base['environment'].items(): old['environment'].setdefault(k,v)
        old.setdefault('replay_tail',[]); old.setdefault('events',[]); old.setdefault('history',[])
        return old
    s=fresh_state()
    s['migration']={'from':old.get('version',1),'at':time.time()}
    s['bankroll']=float(old.get('bankroll',1000)); s['rounds']=int(old.get('rounds',0))
    s['wins_total']=int(old.get('wins_total',0)); s['losses_total']=int(old.get('losses_total',max(0,s['rounds']-s['wins_total'])))
    if old.get('version')==2:
        of=old.get('fly',{}); ob=old.get('brain',{})
        for k in ('energy','hunger','thirst','fatigue','stress','curiosity','mood'):
            if k in of: s['fly'][k]=float(of[k])
        s['fly']['x']=clamp(float(of.get('x',120)),15,WORLD['width']-15)
        s['fly']['y']=clamp(float(of.get('y',770)),15,WORLD['height']-15)
        s['fly']['heading']=float(of.get('heading',-.65))
        s['brain']=fresh_brain(ob)
        s['environment']['machine_p']=list(old.get('environment',{}).get('machine_p',s['environment']['machine_p']))[:3]
        s['history']=copy.deepcopy(old.get('history',[]))[-250:]
        s['events']=copy.deepcopy(old.get('events',[]))[-50:]
        s['visits'].update(old.get('visits',{}))
        for site in SITES:
            if s['visits'].get(site['id'],0)>0:
                s['memory']['known'][site['id']]={'x':site['x'],'y':site['y'],'confidence':.92,'seen':s['ticks']}
        s['events'].append({'text':'V2 memories and learned casino values migrated into V3','kind':'system','tick':s['ticks']})
    else:
        ob={'slot_q':old.get('values',[0,0,0]),'slot_counts':old.get('counts',[0,0,0]),'slot_wins':old.get('wins',[0,0,0])}
        s['brain']=fresh_brain(ob)
        s['history']=copy.deepcopy(old.get('history',[]))[-180:]
        s['events'].append({'text':'Legacy gambling memory migrated into V3','kind':'system','tick':0})
    return s


def load_state():
    os.makedirs(STATE_DIR,exist_ok=True); os.makedirs(CLONE_DIR,exist_ok=True)
    try:
        with open(STATE_FILE) as f: return migrate(json.load(f))
    except Exception:
        return fresh_state()


def atomic_save(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    tmp=path+'.tmp'
    with open(tmp,'w') as f: json.dump(obj,f,separators=(',',':'))
    os.replace(tmp,path)


class Simulation:
    def __init__(self,initial_state=None,start_thread=True,persistent=True):
        self.persistent=persistent
        self.state=migrate(copy.deepcopy(initial_state)) if initial_state is not None else load_state()
        self.brain=Brain(self.state['brain'])
        self.replay=deque(self.state.get('replay_tail',[])[-240:],maxlen=1000)
        self._stop=False; self.last_save=time.time(); self.next_replay=float(self.state.get('sim_seconds',0)); self.rng=random.Random()
        if start_thread:
            self.thread=threading.Thread(target=self._runner,daemon=True); self.thread.start()

    def event(self,text,kind='info'):
        e={'text':text,'kind':kind,'tick':self.state['ticks'],'day':self.state['day'],'clock':round(self.state['clock'],2)}
        self.state['events'].append(e); self.state['events']=self.state['events'][-70:]
        self.state['memory']['episodes'].append(e); self.state['memory']['episodes']=self.state['memory']['episodes'][-150:]

    def save(self):
        if not self.persistent: return
        self.state['replay_tail']=list(self.replay)[-240:]
        atomic_save(STATE_FILE,self.state)

    def _record_action(self,action):
        self.state['fly']['action']=action
        a=self.state['research']['actions']; a[action]=a.get(action,0)+1
        self.state['brain']['activity']['action']=action

    def _known_target(self,site_id):
        m=self.state['memory']['known'].get(site_id)
        return None if not m else (float(m['x']),float(m['y']))

    def perceive(self):
        s=self.state; f=s['fly']; env=s['environment']; light=light_level(s['clock'],env['weather'])
        visible=visible_sites(f,env['weather'],light)
        odors,nearest=odor_field(f,env['weather'])
        threats=hazard_percepts(f,env['hazards'])
        for p in visible:
            site=SITE_BY_ID[p['id']]
            s['memory']['known'][p['id']]={'x':site['x'],'y':site['y'],'confidence':1.0,'seen':s['ticks']}
        # Memory fades slowly for non-home locations, but coordinates are not magically refreshed.
        for sid,m in s['memory']['known'].items():
            if sid!='home' and s['ticks']-m.get('seen',0)>7000:
                m['confidence']=max(.25,m.get('confidence',1.0)-.0007)
        left=center=right=0.0; casino=home=0.0
        for p in visible:
            sal=p['salience']; b=p['bearing']
            if b<-.22: left=max(left,sal)
            elif b>.22: right=max(right,sal)
            else: center=max(center,sal)
            if p['kind']=='casino': casino=max(casino,sal)
            if p['kind']=='home': home=max(home,sal)
        threat=max([p['threat'] for p in threats],default=0.0)
        sensory={'vision_left':left,'vision_center':center,'vision_right':right,
                 'food_odor':odors['food'],'water_odor':odors['water'],'flower_odor':odors['flower'],
                 'casino_cue':max(casino,odors['casino']*.45),'home_cue':max(home,odors['home']),
                 'hazard':threat,'hunger':f['hunger']/100,'thirst':f['thirst']/100,'fatigue':f['fatigue']/100,
                 'stress':f['stress']/100,'novelty':f['curiosity']/100}
        kc=self.brain.encode(sensory); mbon=self.brain.mushroom_body(kc)
        return {'visible':visible,'odors':odors,'nearest_odor':nearest,'threats':threats,'sensory':sensory,'mbon':mbon,'light':light}

    def choose_goal(self,percept,force=False):
        s=self.state; f=s['fly']
        if not force and s['sim_seconds']-f.get('last_goal_sim',-99)<3.5: return
        known=set(s['memory']['known'])
        goal,scores=self.brain.choose_goal(f,percept['mbon'],known,s['bankroll'],self.rng)
        f['goal']=goal; f['last_goal_sim']=s['sim_seconds']; s['brain']['activity']['goal_scores']=scores
        r=s['research']['goal_counts']; r[goal]=r.get(goal,0)+1
        target=None
        if goal in ('food','water','home') and goal in known:
            target=goal
        elif goal=='casino':
            ids=[x for x in ('cherry','lemon','diamond') if x in known]
            if ids:
                available=[SITE_BY_ID[x]['machine'] for x in ids]
                arm=self.brain.choose_machine(available,self.rng); target=('cherry','lemon','diamond')[arm]
        elif goal=='explore' and 'garden' in known and self.rng.random()<.35:
            target='garden'
        f['target']=target
        if target is None:
            # Exploration has no privileged map. Pick a waypoint in egocentric space.
            ang=f['heading']+self.rng.uniform(-1.25,1.25); d=self.rng.uniform(120,330)
            f['waypoint']={'x':clamp(f['x']+math.cos(ang)*d,20,WORLD['width']-20),
                           'y':clamp(f['y']+math.sin(ang)*d,20,WORLD['height']-20)}
        else:
            f['waypoint']=None
        self._record_action('select '+goal)

    def _target_xy(self):
        f=self.state['fly']
        if f.get('target'):
            mem=self.state['memory']['known'].get(f['target'])
            if mem: return float(mem['x']),float(mem['y'])
        wp=f.get('waypoint')
        return (float(wp['x']),float(wp['y'])) if wp else None

    def navigate(self,dt,percept):
        s=self.state; f=s['fly']; target=self._target_xy()
        if target is None:
            self.choose_goal(percept,True); target=self._target_xy()
            if target is None: return
        tx,ty=target; d=distance_xy(f['x'],f['y'],tx,ty); target_bearing=math.atan2(ty-f['y'],tx-f['x'])
        hazard_bearing=None
        if percept['threats'] and percept['threats'][0]['distance']<95:
            hazard_bearing=percept['threats'][0]['bearing']; f['stress']=clamp(f['stress']+5*dt,0,100)
        turn,dnl,dnr=self.brain.navigation(f['heading'],target_bearing,hazard_bearing)
        f['heading']=angle_wrap(f['heading']+turn*2.25*dt+self.rng.uniform(-.025,.025))
        forward=clamp((dnl+dnr)/.7,0,1.25)
        speed=(36+f['energy']*.42)*(0.62 if f['fatigue']>78 else 1.0)*forward
        oldx,oldy=f['x'],f['y']; moved=try_move(f,math.cos(f['heading'])*speed*dt,math.sin(f['heading'])*speed*dt)
        actual=distance_xy(oldx,oldy,f['x'],f['y']); s['research']['distance']+=actual
        if not moved:
            f['heading']=angle_wrap(f['heading']+self.rng.choice([-1,1])*1.15)
            self._record_action('avoid obstacle')
        else: self._record_action('move')
        f['energy']=clamp(f['energy']-.038*dt*(1+forward),0,100); f['hunger']=clamp(f['hunger']+.021*dt,0,100)
        f['thirst']=clamp(f['thirst']+.028*dt,0,100); f['fatigue']=clamp(f['fatigue']+.016*dt,0,100)
        if d<42:
            if f.get('target') and f['target'] in SITE_BY_ID: self.interact(SITE_BY_ID[f['target']],percept)
            else:
                f['curiosity']=clamp(f['curiosity']-8,0,100); self.brain.learn(.4,.55,'general'); self.choose_goal(percept,True)

    def interact(self,site,percept):
        s=self.state; f=s['fly']
        if s['sim_seconds']-f.get('last_action_sim',-99)<2.1: return
        f['last_action_sim']=s['sim_seconds']; s['visits'][site['id']]=s['visits'].get(site['id'],0)+1
        s['memory']['known'][site['id']]={'x':site['x'],'y':site['y'],'confidence':1.0,'seen':s['ticks']}
        reward=0.0; novelty=.15
        if site['kind']=='food':
            self._record_action('feed'); before=f['hunger']; amount=min(62,s['environment']['food_stock'])
            f['hunger']=clamp(f['hunger']-amount,0,100); f['energy']=clamp(f['energy']+30,0,100); f['mood']=clamp(f['mood']+6,0,100)
            s['environment']['food_stock']=clamp(s['environment']['food_stock']-5,0,100); reward=(before-f['hunger'])/13; self.event('Fed on fermenting fruit','food')
        elif site['kind']=='water':
            self._record_action('drink'); before=f['thirst']; f['thirst']=clamp(f['thirst']-74,0,100); f['mood']=clamp(f['mood']+3,0,100)
            reward=(before-f['thirst'])/15; self.event('Drank from the pool','water')
        elif site['kind']=='home':
            self._record_action('sleep'); before=f['fatigue']; f['fatigue']=clamp(f['fatigue']-72,0,100); f['energy']=clamp(f['energy']+48,0,100)
            f['stress']=clamp(f['stress']-28,0,100); reward=(before-f['fatigue'])/14; self.event('Slept in the nest','home')
        elif site['kind']=='explore':
            self._record_action('inspect flowers'); before=f['curiosity']; f['curiosity']=clamp(f['curiosity']-50,0,100); f['mood']=clamp(f['mood']+5,0,100)
            reward=max(.4,(before-f['curiosity'])/28); novelty=.85; self.event('Inspected the flower garden','explore')
        elif site['kind']=='casino':
            self.enter_casino(site); return
        self.brain.learn(reward,novelty,'general'); self.choose_goal(percept,True)

    def enter_casino(self,site):
        f=self.state['fly']; f['indoors']=site['id']; self._record_action('enter casino')
        self.event(f"Entered {site['name']}",'casino')
        self.gamble(site['machine'])

    def _choose_wager(self,arm):
        s=self.state; f=s['fly']; q=s['brain']['slot_q'][arm]; risk=MACHINES[arm]['risk']
        base=1
        if s['bankroll']>150: base=2
        if s['bankroll']>500: base=5
        if s['bankroll']>1500: base=10
        appetite=clamp((q+6)/18,0,1); stress_penalty=f['stress']/120
        scale=1+risk*appetite-stress_penalty
        wager=max(1,round(base*clamp(scale,.45,2.4)))
        return min(wager,max(1,int(s['bankroll'])))

    def gamble(self,arm):
        s=self.state; f=s['fly']; env=s['environment']; m=MACHINES[arm]
        if s['bankroll']<=0:
            f['indoors']=None; self.event('No FlyBucks left; walked away','loss'); return
        wager=self._choose_wager(arm); p=env['machine_p'][arm]; win=self.rng.random()<p
        reward=round(wager*m['multiplier'],2) if win else -float(wager)
        if f.get('last_bet_reward') is not None and f['last_bet_reward']<0:
            s['research']['loss_opportunities']+=1; s['research']['bets_after_loss']+=1
        f['last_bet_reward']=reward; f['casino_streak']=int(f.get('casino_streak',0))+1
        pe_q=self.brain.update_machine(arm,reward); pe_mb=self.brain.learn(reward,0.10,'casino')
        s['bankroll']=round(max(0,s['bankroll']+reward),2); s['rounds']+=1; s['research']['wagers'].append(wager); s['research']['wagers']=s['research']['wagers'][-500:]
        if reward>0:
            s['wins_total']+=1; f['mood']=clamp(f['mood']+6,0,100); f['stress']=clamp(f['stress']-2,0,100)
        else:
            s['losses_total']+=1; f['mood']=clamp(f['mood']-4,0,100); f['stress']=clamp(f['stress']+3+2*m['risk'],0,100)
        h={'type':'gamble','round':s['rounds'],'machine':arm,'wager':wager,'reward':reward,'bankroll':s['bankroll'],
           'pe':round(pe_q,3),'mb_pe':round(pe_mb,3),'day':s['day'],'time':round(s['clock'],2),'streak':f['casino_streak']}
        s['history'].append(h); s['history']=s['history'][-500:]
        self._record_action('gamble'); self.event(f"{m['name']} wager F฿{wager}: {reward:+.1f}",'win' if reward>0 else 'loss')
        # Stay/leave is itself a learned behavioral choice. Loss-chasing can emerge from high learned value and low stress.
        q=s['brain']['slot_q'][arm]; stay_drive=.48 + clamp(q/20,-.25,.28) - f['stress']/180
        if reward<0: stay_drive += clamp(q/28,-.08,.22)
        if f['hunger']>76 or f['thirst']>76 or f['fatigue']>82 or s['bankroll']<2: stay_drive-=.55
        if self.rng.random()<clamp(stay_drive,.04,.92):
            self._record_action('stay in casino')
        else:
            f['indoors']=None; f['casino_streak']=0; self._record_action('leave casino'); self.event(f"Left {m['name']} after deciding to walk away",'casino')

    def casino_tick(self,dt,percept):
        s=self.state; f=s['fly']; s['research']['casino_seconds']+=dt
        if f['indoors'] not in SITE_BY_ID:
            f['indoors']=None; return
        if s['sim_seconds']-f.get('last_action_sim',-99)>3.4:
            f['last_action_sim']=s['sim_seconds']; self.gamble(SITE_BY_ID[f['indoors']]['machine'])
            if f['indoors'] is None: self.choose_goal(percept,True)

    def homeostasis(self,dt):
        s=self.state; f=s['fly']; weather=s['environment']['weather']
        f['curiosity']=clamp(f['curiosity']+.010*dt,0,100)
        if s['clock']<6 or s['clock']>22: f['fatigue']=clamp(f['fatigue']+.030*dt,0,100)
        if weather=='heat': f['thirst']=clamp(f['thirst']+.035*dt,0,100)
        if f['hunger']>92 or f['thirst']>92:
            f['health']=clamp(f['health']-.06*dt*(1+(f['hunger']+f['thirst']-184)/16),0,100)
            f['stress']=clamp(f['stress']+.04*dt,0,100)
        else: f['health']=clamp(f['health']+.012*dt,0,100)
        if f['health']<=0:
            f.update({'x':110,'y':770,'health':55,'energy':40,'hunger':65,'thirst':65,'fatigue':45,'stress':80,'indoors':None})
            self.brain.learn(-15,.1,'general'); self.event('Fly collapsed and recovered at the nest','loss')

    def world_event(self):
        s=self.state; env=s['environment']; env['drift_epoch']+=1
        env['machine_p']=[clamp(m['base_p']+self.rng.uniform(-.10,.10),.025,.80) for m in MACHINES]
        env['weather']=self.rng.choices(['clear','wind','mist','rain','heat'],[45,18,12,13,12])[0]
        env['event']=f"{env['weather'].title()} weather; casino schedules changed"
        self.event(env['event'],'world')

    def record_replay(self,percept):
        s=self.state; f=s['fly']; a=s['brain']['activity']
        frame={'t':round(s['sim_seconds'],2),'day':s['day'],'clock':round(s['clock'],3),'x':round(f['x'],1),'y':round(f['y'],1),
               'heading':round(f['heading'],3),'goal':f['goal'],'target':f.get('target'),'action':f['action'],'bankroll':s['bankroll'],
               'needs':{k:round(f[k],1) for k in ('energy','hunger','thirst','fatigue','stress','curiosity','health')},
               'visible':[x['id'] for x in percept['visible']],'sensory':a.get('sensory',{}),'mbon':a.get('mbon',{}),
               'dan':a.get('dan',{}),'epg':a.get('epg',[]),'motor':a.get('motor',{})}
        self.replay.append(frame)

    def update_heatmap(self,dt):
        s=self.state; f=s['fly']; cols,rows=28,18
        cx=min(cols-1,max(0,int(f['x']/WORLD['width']*cols))); cy=min(rows-1,max(0,int(f['y']/WORLD['height']*rows)))
        idx=cy*cols+cx; s['research']['heatmap'][idx]+=round(dt,3)
        if f['goal']=='explore': s['research']['explore_seconds']+=dt
        dan=s['brain']['activity'].get('dan',{}); d=dan.get('PAM_reward',0)-dan.get('PPL1_punishment',0)
        if abs(d)>.001:
            s['research']['dopamine'].append({'t':round(s['sim_seconds'],1),'v':round(d,3)})
            s['research']['dopamine']=s['research']['dopamine'][-500:]

    def tick(self,dt):
        s=self.state; dt=min(dt,2.5); s['ticks']+=1; s['sim_seconds']+=dt; s['clock']+=dt/60
        if s['clock']>=24: s['clock']-=24; s['day']+=1
        update_hazards(s['environment']['hazards'],dt); self.homeostasis(dt)
        s['environment']['food_stock']=clamp(s['environment']['food_stock']+.014*dt,0,100)
        s['environment']['water_stock']=clamp(s['environment']['water_stock']+.020*dt,0,100)
        if s['ticks']%1800==0: self.world_event()
        percept=self.perceive(); self.choose_goal(percept)
        if s['fly'].get('indoors'): self.casino_tick(dt,percept)
        else: self.navigate(dt,percept)
        self.update_heatmap(dt)
        if s['sim_seconds']>=self.next_replay:
            self.record_replay(percept); self.next_replay=s['sim_seconds']+1.5
        if self.persistent and time.time()-self.last_save>3.0:
            self.save(); self.last_save=time.time()

    def _runner(self):
        last=time.time()
        while not self._stop:
            time.sleep(.035); now=time.time(); real=min(.15,now-last); last=now
            with LOCK:
                if self.state.get('running',True): self.tick(real*float(self.state.get('speed',1.0)))

    def personality(self):
        s=self.state; b=s['brain']; counts=b['slot_counts']; total=max(1,sum(counts)); wagers=s['research']['wagers']
        risk=sum(counts[i]*MACHINES[i]['risk'] for i in range(3))/total
        loyalty=max(counts)/total if total else 0
        chase=s['research']['bets_after_loss']/max(1,s['research']['loss_opportunities'])
        avg_wager=sum(wagers)/max(1,len(wagers))
        action_total=max(1,sum(s['research']['actions'].values())); explore=s['research']['actions'].get('inspect flowers',0)/action_total
        # Shannon entropy of machine preference.
        entropy=0.0
        for c in counts:
            if c: p=c/total; entropy-=p*math.log(p,2)
        return {'risk_preference':round(risk,3),'machine_loyalty':round(loyalty,3),'loss_chasing':round(chase,3),
                'avg_wager':round(avg_wager,2),'novelty_seeking':round(explore,3),'choice_entropy':round(entropy,3),
                'reward_sensitivity':round(b.get('reward_sensitivity',1),2),'punishment_sensitivity':round(b.get('punishment_sensitivity',1),2)}

    def snapshot(self):
        with LOCK:
            s=copy.deepcopy(self.state)
        s.pop('replay_tail',None); s['world']=WORLD; s['sites']=SITES; s['walls']=WALLS; s['personality']=self.personality()
        s['machines']=[]
        for i,m in enumerate(MACHINES):
            c=s['brain']['slot_counts'][i]; w=s['brain']['slot_wins'][i]
            s['machines'].append({**m,'q':round(s['brain']['slot_q'][i],3),'count':c,'wins':w,'win_rate':round(100*w/max(1,c),1),
                                  'current_p':round(100*s['environment']['machine_p'][i],1)})
        s['favorite']=max(range(3),key=lambda i:s['brain']['slot_q'][i])
        # The UI gets summary weights, not all 768 plastic synapses on every poll.
        s['brain']['weight_summary']={k:round(sum(v)/len(v),4) for k,v in s['brain']['mb_weights'].items()}
        s['brain'].pop('mb_weights',None); s['brain'].pop('eligibility',None)
        return s

    def control(self,action,value=None):
        with LOCK:
            if action=='start': self.state['running']=True
            elif action=='pause': self.state['running']=False
            elif action=='speed': self.state['speed']=clamp(float(value),.25,200)
            elif action=='world_event': self.world_event()
            elif action=='return_home':
                f=self.state['fly']; f.update({'x':110,'y':770,'indoors':None,'target':'home','waypoint':None}); self.event('Observer returned fly to nest; learning preserved','system')
            elif action=='reset':
                self.state=fresh_state(); self.brain=Brain(self.state['brain']); self.replay.clear(); self.state['running']=False; self.event('Fresh V3 organism created','system')
            else: raise ValueError('unknown action')
            self.save(); return self.snapshot()

    def set_intervention(self,name,value):
        allowed={'learning','dopamine','motor_gain','silenced','activated','sensory_mask'}
        if name not in allowed: raise ValueError('unknown intervention')
        with LOCK:
            iv=self.state['brain']['interventions']
            if name in ('learning','dopamine'): iv[name]=bool(value)
            elif name=='motor_gain': iv[name]=clamp(float(value),0,2.5)
            else: iv[name]=list(value or [])
            self.state['research']['interventions_log'].append({'t':round(self.state['sim_seconds'],1),'name':name,'value':copy.deepcopy(iv[name])})
            self.state['research']['interventions_log']=self.state['research']['interventions_log'][-100:]
            self.event(f"Intervention: {name} = {iv[name]}",'system'); self.save(); return self.snapshot()

    def clone_current(self,label='clone'):
        with LOCK: data=copy.deepcopy(self.state)
        cid=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]
        data['clone_meta']={'id':cid,'label':str(label)[:80],'created':time.time()}
        atomic_save(os.path.join(CLONE_DIR,cid+'.json'),data)
        return data['clone_meta']

    def list_clones(self):
        os.makedirs(CLONE_DIR,exist_ok=True); out=[]
        for fn in sorted(os.listdir(CLONE_DIR),reverse=True)[:30]:
            if not fn.endswith('.json'): continue
            try:
                d=json.load(open(os.path.join(CLONE_DIR,fn))); meta=d.get('clone_meta',{'id':fn[:-5],'label':fn[:-5]})
                meta.update({'bankroll':d.get('bankroll'),'rounds':d.get('rounds'),'day':d.get('day')}); out.append(meta)
            except Exception: pass
        return out

    def activate_clone(self,cid):
        path=os.path.join(CLONE_DIR,os.path.basename(cid)+'.json')
        with open(path) as f: data=migrate(json.load(f))
        with LOCK:
            data.pop('clone_meta',None); self.state=data; self.brain=Brain(self.state['brain']); self.replay=deque(self.state.get('replay_tail',[]),maxlen=1000)
            self.event(f"Activated clone {cid}",'system'); self.save()
        return self.snapshot()

    def run_experiment(self,treatment='dopamine_off',steps=1600):
        steps=max(200,min(int(steps),6000)); base=copy.deepcopy(self.state)
        base['running']=True; base['speed']=1
        results=[]
        for label in ('control','treatment'):
            st=copy.deepcopy(base)
            if label=='treatment':
                iv=st['brain']['interventions']
                if treatment=='dopamine_off': iv['dopamine']=False
                elif treatment=='learning_off': iv['learning']=False
                elif treatment=='PFL3_off': iv['silenced']=list(set(iv.get('silenced',[])+['PFL3']))
                elif treatment=='MBON_off': iv['silenced']=list(set(iv.get('silenced',[])+['MBON']))
            sandbox=Simulation(st,start_thread=False,persistent=False); sandbox.rng.seed(8842)
            start_rounds=sandbox.state['rounds']; start_bank=sandbox.state['bankroll']; start_dist=sandbox.state['research']['distance']
            for _ in range(steps): sandbox.tick(.35)
            ps=sandbox.personality(); results.append({'group':label,'treatment':treatment if label=='treatment' else 'none',
                'wagers':sandbox.state['rounds']-start_rounds,'bankroll_delta':round(sandbox.state['bankroll']-start_bank,2),
                'distance':round(sandbox.state['research']['distance']-start_dist,1),'health':round(sandbox.state['fly']['health'],1),
                'casino_seconds':round(sandbox.state['research']['casino_seconds'],1),'personality':ps})
        record={'id':uuid.uuid4().hex[:8],'treatment':treatment,'steps':steps,'created':time.time(),'results':results}
        with LOCK:
            self.state['research']['experiments'].append(record); self.state['research']['experiments']=self.state['research']['experiments'][-20:]; self.save()
        return record

    def replay_frames(self,limit=400):
        return list(self.replay)[-max(1,min(int(limit),1000)):]
