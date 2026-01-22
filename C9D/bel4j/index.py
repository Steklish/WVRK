import json
class Index:
    def __init__(self, db):
        self.db = db
        self.db.execute("CREATE TABLE IF NOT EXISTS idx(label TEXT, prop_key TEXT, prop_val TEXT, node_id TEXT)")

    def add_node(self, nid, labels, props):
        for l in labels:
            for k, v in props.items():
                self.db.execute("INSERT INTO idx(label,prop_key,prop_val,node_id) VALUES(?,?,?,?)",
                               (l, k, str(v), nid))
    
    def drop_node(self, nid):
        self.db.execute("DELETE FROM idx WHERE node_id=?", (nid,))

    def update_node(self, nid, props):
        self.drop_node(nid)
        row = self.db.execute("SELECT labels FROM nodes WHERE id=?", (nid,)).fetchone()
        if row:
            labels = set(json.loads(row[0]))
            self.add_node(nid, labels, props)
            
    def lookup(self, label, key, val) -> list[str]:
        cur = self.db.execute("SELECT node_id FROM idx WHERE label=? AND prop_key=? AND prop_val=?",
                             (label, key, str(val)))
        return [row[0] for row in cur]