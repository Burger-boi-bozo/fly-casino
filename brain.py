import math, random
from world import angle_wrap, clamp

SENSORY_KEYS = [
    'vision_left','vision_center','vision_right','food_odor','water_odor','flower_odor',
    'casino_cue','home_cue','hazard','hunger','thirst','fatigue','stress','novelty'
]
KC_N = 192
EPG_N = 16


def _seeded_projection(seed):
    rng=random.Random(seed)
    proj=[]
    for _ in range(KC_N):
        idx=rng.sample(range(len(SENSORY_KEYS)),4)
        weights=[rng.uniform(.65,1.35) for _ in idx]
        proj.append(list(zip(idx,weights)))
    return proj


def _ring(angle,n=EPG_N,width=.62):
    vals=[]
    for i in range(n):
        pref=-math.pi + (2*math.pi*i/n)
        d=angle_wrap(angle-pref)
        vals.append(math.exp(-(d*d)/(2*width*width)))
    m=max(vals) or 1
    return [v/m for v in vals]


def fresh_brain(old=None):
    old=old or {}
    slot_q=list(old.get('slot_q',[0.0,0.0,0.0]))[:3]
    counts=list(old.get('slot_counts',[0,0,0]))[:3]
    wins=list(old.get('slot_wins',[0,0,0]))[:3]
    while len(slot_q)<3: slot_q.append(0.0)
    while len(counts)<3: counts.append(0)
    while len(wins)<3: wins.append(0)
    rng=random.Random(33017)
    return {
        'model':'v3-connectome-inspired','kc_n':KC_N,'seed':33017,
        'slot_q':slot_q,'slot_counts':counts,'slot_wins':wins,
        'alpha':float(old.get('alpha',.055)),'temperature':2.2,'epsilon':.065,
        'mb_weights':{
            'appetitive':[rng.uniform(-.08,.08) for _ in range(KC_N)],
            'aversive':[rng.uniform(-.08,.08) for _ in range(KC_N)],
            'gambling':[rng.uniform(-.05,.05) for _ in range(KC_N)],
            'novelty':[rng.uniform(-.05,.05) for _ in range(KC_N)],
        },
        'eligibility':[0.0]*KC_N,
        'activity':{'sensory':{},'kc_sparse':[],'mbon':{},'dan':{},'epg':[0.0]*EPG_N,
                    'goal_ring':[0.0]*EPG_N,'pfl3':{'left':0.0,'right':0.0},
                    'motor':{'DNa02_L':0.0,'DNa02_R':0.0},'action':'idle'},
        'interventions':{'learning':True,'dopamine':True,'silenced':[],'activated':[],
                         'sensory_mask':[],'motor_gain':1.0},
        'last_prediction_error':0.0,'last_reward':0.0,'reward_sensitivity':1.0,
        'punishment_sensitivity':1.0,'learning_events':0,
    }


class Brain:
    def __init__(self,state):
        self.state=state
        self.projection=_seeded_projection(int(state.get('seed',33017)))
        self.last_kc=[0.0]*KC_N

    def interventions(self):
        return self.state['interventions']

    def _suppressed(self,name):
        iv=self.interventions()
        return name in iv.get('silenced',[])

    def _boost(self,name,value):
        iv=self.interventions()
        return max(value,1.0) if name in iv.get('activated',[]) else value

    def encode(self,sensory):
        iv=self.interventions(); masked=set(iv.get('sensory_mask',[]))
        vec=[]
        for key in SENSORY_KEYS:
            v=0.0 if key in masked else float(sensory.get(key,0.0))
            vec.append(clamp(v,0,1))
        raw=[]
        for conns in self.projection:
            z=sum(vec[i]*w for i,w in conns)/len(conns)
            raw.append(max(0.0,z-.22))
        k=max(10,int(KC_N*.11)); threshold=sorted(raw,reverse=True)[k-1]
        kc=[(v if v>=threshold and v>0 else 0.0) for v in raw]
        mx=max(kc) if kc else 1
        if mx>0: kc=[v/mx for v in kc]
        self.last_kc=kc
        active=[i for i,v in enumerate(kc) if v>0]
        self.state['activity']['sensory']={k:round(vec[i],3) for i,k in enumerate(SENSORY_KEYS)}
        self.state['activity']['kc_sparse']=active[:32]
        # Eligibility lets delayed reinforcement update recently active KCs.
        self.state['eligibility']=[max(e*.91,kc[i]) for i,e in enumerate(self.state['eligibility'])]
        return kc

    def mushroom_body(self,kc):
        out={}
        for channel,weights in self.state['mb_weights'].items():
            num=sum(kc[i]*weights[i] for i in range(KC_N))
            den=max(1.0,sum(1 for v in kc if v>0))
            out[channel]=num/den*8.0
        if self._suppressed('MBON'):
            out={k:0.0 for k in out}
        for k in out:
            out[k]=self._boost('MBON_'+k,out[k])
        self.state['activity']['mbon']={k:round(v,4) for k,v in out.items()}
        return out

    def learn(self,reward,novelty=0.0,context='general'):
        pe=float(reward)-self.state.get('last_reward',0.0)*.18
        self.state['last_prediction_error']=pe; self.state['last_reward']=float(reward)
        positive=max(0,pe)*self.state.get('reward_sensitivity',1.0)
        negative=max(0,-pe)*self.state.get('punishment_sensitivity',1.0)
        dan={'PAM_reward':clamp(positive/12,0,1),'PPL1_punishment':clamp(negative/12,0,1),
             'novelty':clamp(novelty,0,1)}
        if not self.interventions().get('dopamine',True) or self._suppressed('DAN'):
            dan={k:0.0 for k in dan}
        for k in dan: dan[k]=self._boost('DAN_'+k,dan[k])
        self.state['activity']['dan']={k:round(v,4) for k,v in dan.items()}
        if not self.interventions().get('learning',True):
            return pe
        lr=self.state['alpha']
        elig=self.state['eligibility']
        # A compact approximation of compartmental KC→MBON plasticity.
        for i,e in enumerate(elig):
            if e<=0: continue
            self.state['mb_weights']['appetitive'][i]=clamp(self.state['mb_weights']['appetitive'][i]+lr*e*dan['PAM_reward']*.42,-1.5,1.5)
            self.state['mb_weights']['aversive'][i]=clamp(self.state['mb_weights']['aversive'][i]+lr*e*dan['PPL1_punishment']*.42,-1.5,1.5)
            if context=='casino':
                delta=(dan['PAM_reward']-dan['PPL1_punishment'])*lr*e*.50
                self.state['mb_weights']['gambling'][i]=clamp(self.state['mb_weights']['gambling'][i]+delta,-1.5,1.5)
            self.state['mb_weights']['novelty'][i]=clamp(self.state['mb_weights']['novelty'][i]+lr*e*dan['novelty']*.12,-1.0,1.0)
        self.state['learning_events']+=1
        return pe

    def navigation(self,heading,target_bearing,hazard_bearing=None):
        epg=_ring(heading); goal=_ring(target_bearing)
        err=angle_wrap(target_bearing-heading)
        # PFL3-like opponent steering signal, with an avoidance offset for a nearby threat.
        avoid=0.0
        if hazard_bearing is not None:
            avoid=-math.copysign(.9,hazard_bearing if abs(hazard_bearing)>.05 else .05)
        command=clamp(math.sin(err)*1.35+avoid,-1,1)
        left=max(0, command); right=max(0,-command)
        if self._suppressed('PFL3'): left=right=0
        left=self._boost('PFL3_L',left); right=self._boost('PFL3_R',right)
        gain=float(self.interventions().get('motor_gain',1.0))
        dna_l=clamp((.35+right-left*.55)*gain,0,1.5)
        dna_r=clamp((.35+left-right*.55)*gain,0,1.5)
        if self._suppressed('DNa02'): dna_l=dna_r=0
        self.state['activity']['epg']=[round(v,3) for v in epg]
        self.state['activity']['goal_ring']=[round(v,3) for v in goal]
        self.state['activity']['pfl3']={'left':round(left,3),'right':round(right,3)}
        self.state['activity']['motor']={'DNa02_L':round(dna_l,3),'DNa02_R':round(dna_r,3)}
        return command,dna_l,dna_r

    def goal_scores(self,fly,mbon,known,bankroll):
        scores={
            'food':fly['hunger']*.105 + max(0,mbon.get('appetitive',0))*.28,
            'water':fly['thirst']*.118,
            'home':fly['fatigue']*.108 + max(0,fly['stress']-48)*.055,
            'explore':fly['curiosity']*.066 + max(0,mbon.get('novelty',0))*.35,
            'casino':max(0,62-fly['stress'])*.021 + mbon.get('gambling',0)*.52 + max(self.state['slot_q'])*.12,
        }
        for k in ('food','water','home'):
            if k not in known: scores[k]-=1.0
        if not any(x in known for x in ('cherry','lemon','diamond')): scores['casino']-=1.3
        if bankroll<10: scores['casino']-=4.5
        if fly['health']<45: scores['home']+=4.0
        if fly['energy']<18: scores['home']+=3.5
        return scores

    def choose_goal(self,fly,mbon,known,bankroll,rng=random):
        scores=self.goal_scores(fly,mbon,known,bankroll)
        keys=list(scores); vals=[scores[k] for k in keys]
        # Noisy softmax preserves spontaneous exploration without omniscient targeting.
        temp=1.10
        m=max(vals); ex=[math.exp((v-m)/temp) for v in vals]
        r=rng.random()*sum(ex); a=0
        choice=keys[-1]
        for k,p in zip(keys,ex):
            a+=p
            if r<=a: choice=k; break
        return choice,{k:round(v,3) for k,v in scores.items()}

    def choose_machine(self,available=(0,1,2),rng=random):
        q=self.state['slot_q']; eps=self.state['epsilon']
        if rng.random()<eps: return rng.choice(list(available))
        temp=max(.25,self.state['temperature']); vals=[q[i] for i in available]; m=max(vals)
        ex=[math.exp((v-m)/temp) for v in vals]; r=rng.random()*sum(ex); a=0
        for idx,p in zip(available,ex):
            a+=p
            if r<=a: return idx
        return list(available)[-1]

    def update_machine(self,arm,reward):
        old=self.state['slot_q'][arm]
        pe=reward-old
        if self.interventions().get('learning',True) and self.interventions().get('dopamine',True):
            self.state['slot_q'][arm]=old+self.state['alpha']*pe
        self.state['slot_counts'][arm]+=1
        if reward>0: self.state['slot_wins'][arm]+=1
        return pe

    def graph(self):
        nodes=[]; edges=[]
        for i,k in enumerate(SENSORY_KEYS): nodes.append({'id':'S_'+k,'label':k,'group':'sensory'})
        for i in range(KC_N): nodes.append({'id':f'KC{i:03}','label':f'KC {i}','group':'Kenyon cell'})
        for i in range(EPG_N): nodes.append({'id':f'EPG{i:02}','label':f'EPG {i}','group':'central complex'})
        for name in ('MBON_appetitive','MBON_aversive','MBON_gambling','MBON_novelty','DAN_PAM','DAN_PPL1','PFL3_L','PFL3_R','DNa02_L','DNa02_R'):
            nodes.append({'id':name,'label':name.replace('_',' '),'group':'output'})
        # Return representative explicit edges instead of every KC edge to keep browser payload small.
        for kci,conns in enumerate(self.projection[:48]):
            for si,w in conns: edges.append({'source':'S_'+SENSORY_KEYS[si],'target':f'KC{kci:03}','weight':round(w,3),'kind':'sensory→KC'})
            edges.append({'source':f'KC{kci:03}','target':'MBON_gambling','weight':round(self.state['mb_weights']['gambling'][kci],3),'kind':'plastic'})
        for i in range(EPG_N):
            edges.append({'source':f'EPG{i:02}','target':'PFL3_L' if i<EPG_N/2 else 'PFL3_R','weight':1,'kind':'heading'})
        edges += [
            {'source':'DAN_PAM','target':'MBON_gambling','weight':1,'kind':'modulatory'},
            {'source':'DAN_PPL1','target':'MBON_gambling','weight':-1,'kind':'modulatory'},
            {'source':'PFL3_L','target':'DNa02_R','weight':1,'kind':'steering'},
            {'source':'PFL3_R','target':'DNa02_L','weight':1,'kind':'steering'},
        ]
        return {'nodes':nodes,'edges':edges,'kc_total':KC_N,'note':'Population/circuit model inspired by FlyWire anatomy; not a biophysical whole-brain emulator.'}
