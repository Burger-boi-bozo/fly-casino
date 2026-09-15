import math

WIDTH, HEIGHT = 1400, 900
WORLD = {'width': WIDTH, 'height': HEIGHT}

SITES = [
    {'id':'home','name':'Nest','kind':'home','x':110,'y':770,'r':55,'icon':'🏠','odor':None},
    {'id':'food','name':'Fermenting Fruit','kind':'food','x':255,'y':170,'r':52,'icon':'🍎','odor':'food'},
    {'id':'water','name':'Water Pool','kind':'water','x':690,'y':115,'r':48,'icon':'💧','odor':'water'},
    {'id':'garden','name':'Flower Garden','kind':'explore','x':575,'y':505,'r':72,'icon':'🌼','odor':'flower'},
    {'id':'cherry','name':'Cherry House','kind':'casino','machine':0,'x':1060,'y':190,'r':62,'icon':'🍒','odor':'casino'},
    {'id':'lemon','name':'Lemon Lounge','kind':'casino','machine':1,'x':1190,'y':455,'r':62,'icon':'🍋','odor':'casino'},
    {'id':'diamond','name':'Diamond Den','kind':'casino','machine':2,'x':1000,'y':745,'r':62,'icon':'💎','odor':'casino'},
]
SITE_BY_ID = {s['id']: s for s in SITES}

MACHINES = [
    {'name':'Cherry','icon':'🍒','base_p':0.58,'multiplier':0.8,'risk':0.20},
    {'name':'Lemon','icon':'🍋','base_p':0.31,'multiplier':2.1,'risk':0.55},
    {'name':'Diamond','icon':'💎','base_p':0.085,'multiplier':8.5,'risk':1.00},
]

# Rectangular obstacles. Casinos are zones, not impassable buildings, so the fly can enter them.
WALLS = [
    {'x':370,'y':90,'w':42,'h':255,'name':'hedge'},
    {'x':370,'y':605,'w':42,'h':220,'name':'hedge'},
    {'x':765,'y':235,'w':45,'h':280,'name':'wall'},
    {'x':765,'y':650,'w':45,'h':175,'name':'wall'},
    {'x':875,'y':355,'w':215,'h':38,'name':'arcade wall'},
    {'x':1265,'y':90,'w':35,'h':210,'name':'fence'},
]

HAZARDS = [
    {'id':'spider','name':'Tiny Spider','kind':'hazard','x':690.0,'y':700.0,'vx':34.0,'vy':-22.0,'r':22,'icon':'🕷️'},
    {'id':'fan','name':'Air Current','kind':'hazard','x':460.0,'y':300.0,'vx':-20.0,'vy':28.0,'r':30,'icon':'💨'},
]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def angle_wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def distance_xy(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def in_rect(x, y, rect, pad=0):
    return rect['x'] - pad <= x <= rect['x'] + rect['w'] + pad and rect['y'] - pad <= y <= rect['y'] + rect['h'] + pad


def segment_intersects_rect(x1, y1, x2, y2, rect):
    # Conservative sampled line-of-sight check; cheap enough for this small world.
    steps = max(3, int(distance_xy(x1, y1, x2, y2) / 16))
    for i in range(1, steps):
        t = i / steps
        if in_rect(x1 + (x2-x1)*t, y1 + (y2-y1)*t, rect, 2):
            return True
    return False


def line_of_sight(x1, y1, x2, y2):
    return not any(segment_intersects_rect(x1, y1, x2, y2, r) for r in WALLS)


def visible_sites(fly, weather='clear', light=1.0):
    fov = math.radians(118)
    base_range = 285.0 * (0.55 + 0.45 * light)
    if weather == 'mist':
        base_range *= 0.65
    out = []
    for site in SITES:
        d = distance_xy(fly['x'], fly['y'], site['x'], site['y'])
        if d > base_range + site['r']:
            continue
        bearing = math.atan2(site['y']-fly['y'], site['x']-fly['x'])
        rel = angle_wrap(bearing - fly['heading'])
        if abs(rel) <= fov/2 and line_of_sight(fly['x'], fly['y'], site['x'], site['y']):
            out.append({'id':site['id'],'kind':site['kind'],'distance':round(d,2),'bearing':round(rel,4),
                        'salience':round(clamp(1-d/max(1,base_range),0,1),3)})
    return out


def odor_field(fly, weather='clear'):
    wind = 1.25 if weather == 'wind' else (0.75 if weather == 'rain' else 1.0)
    signals = {'food':0.0,'water':0.0,'flower':0.0,'casino':0.0,'home':0.0}
    nearest = {}
    for site in SITES:
        d = distance_xy(fly['x'], fly['y'], site['x'], site['y'])
        channel = site.get('odor') or ('home' if site['kind']=='home' else None)
        if not channel:
            continue
        scale = {'food':260,'water':210,'flower':230,'casino':150,'home':125}.get(channel,180)
        strength = math.exp(-d/(scale*wind))
        if channel == 'casino':
            strength *= 0.60
        signals[channel] = max(signals[channel], strength)
        if channel not in nearest or d < nearest[channel][0]:
            nearest[channel] = (d, site['id'])
    return {k:round(clamp(v,0,1),4) for k,v in signals.items()}, {k:v[1] for k,v in nearest.items()}


def hazard_percepts(fly, hazards):
    out=[]
    for h in hazards:
        d=distance_xy(fly['x'],fly['y'],h['x'],h['y'])
        if d < 220 and line_of_sight(fly['x'],fly['y'],h['x'],h['y']):
            rel=angle_wrap(math.atan2(h['y']-fly['y'],h['x']-fly['x'])-fly['heading'])
            if abs(rel) < math.radians(80):
                out.append({'id':h['id'],'distance':round(d,2),'bearing':round(rel,4),'threat':round(clamp(1-d/220,0,1),3)})
    return out


def update_hazards(hazards, dt):
    for h in hazards:
        h['x'] += h['vx'] * dt
        h['y'] += h['vy'] * dt
        if h['x'] < 40 or h['x'] > WIDTH-40:
            h['vx'] *= -1; h['x']=clamp(h['x'],40,WIDTH-40)
        if h['y'] < 40 or h['y'] > HEIGHT-40:
            h['vy'] *= -1; h['y']=clamp(h['y'],40,HEIGHT-40)
        for r in WALLS:
            if in_rect(h['x'],h['y'],r,h['r']):
                h['vx'] *= -1; h['vy'] *= -1
    return hazards


def try_move(fly, dx, dy):
    nx=clamp(fly['x']+dx,12,WIDTH-12); ny=clamp(fly['y']+dy,12,HEIGHT-12)
    if not any(in_rect(nx,ny,r,10) for r in WALLS):
        fly['x'],fly['y']=nx,ny; return True
    # Try sliding along each axis.
    if not any(in_rect(nx,fly['y'],r,10) for r in WALLS):
        fly['x']=nx; return True
    if not any(in_rect(fly['x'],ny,r,10) for r in WALLS):
        fly['y']=ny; return True
    return False


def light_level(clock, weather='clear'):
    if 7 <= clock <= 19:
        base=1.0
    elif 5.5 <= clock < 7 or 19 < clock <= 21:
        base=0.55
    else:
        base=0.20
    if weather in ('rain','mist'):
        base*=0.78
    return round(base,3)
