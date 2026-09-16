import json, os, random

HERE=os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH=os.path.join(HERE,'data','connectome_v783_subset.json')

class ConnectomeCatalog:
    def __init__(self,path=CATALOG_PATH):
        with open(path) as f: self.data=json.load(f)
        self.circuits=self.data['circuits']

    def summary(self):
        modeled={'KC':'imported','MBON':'imported','PAM':'imported','PPL1':'imported','EPG':'imported','PFL3':'imported','DNa02':'imported','PN':'imported','VISUAL':'imported'}
        return {
            'dataset':self.data.get('dataset'),'license':self.data.get('license'),'source':self.data.get('source'),
            'counts':{k:len(v) for k,v in self.circuits.items()},'coverage':modeled,
            'disclaimer':'FlyWire identities/annotations are real v783 public data; neural dynamics and selected functional couplings are simulated.'
        }

    def cells(self,circuit,limit=50):
        return self.circuits.get(circuit,[])[:max(1,min(int(limit),250))]

    def cell(self,circuit,index):
        cells=self.circuits.get(circuit,[])
        return cells[index%len(cells)] if cells else None

    def sample(self,circuit,n=8,seed=1):
        cells=list(self.circuits.get(circuit,[])); r=random.Random(seed)
        return r.sample(cells,min(len(cells),n))

CATALOG=ConnectomeCatalog()
