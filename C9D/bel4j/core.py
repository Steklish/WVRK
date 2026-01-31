from __future__ import annotations
import sqlite3, json, uuid
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Set
try:
    from .index import Index
except ImportError:
    from index import Index

@dataclass
class Node:
    id: str
    labels: Set[str]
    props: Dict[str, Any]

@dataclass
class Relationship:
    id: str
    start: str  
    end: str
    type: str
    props: Dict[str, Any]

class Graph:
    def __init__(self, db_path: str = "bel4j.db"):
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.text_factory = str
        self.db.isolation_level = None
        self._init_schema()
        self.index = Index(self.db)

    # ---------- schema ----------
    def _init_schema(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS nodes(
                id TEXT PRIMARY KEY,
                labels TEXT NOT NULL,
                props TEXT NOT NULL)
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS rels(
                id TEXT PRIMARY KEY,
                start_id TEXT NOT NULL,
                end_id TEXT NOT NULL,
                type TEXT NOT NULL,
                props TEXT NOT NULL,
                FOREIGN KEY(start_id) REFERENCES nodes(id) ON DELETE CASCADE,
                FOREIGN KEY(end_id) REFERENCES nodes(id) ON DELETE CASCADE)
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS idx(
                label TEXT,
                prop_key TEXT,
                prop_val TEXT,
                node_id TEXT,
                FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE)
        """)
        
        # Дополнительные индексы для производительности
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_label ON idx(label)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_key_val ON idx(prop_key, prop_val)")
        self.db.execute("PRAGMA foreign_keys = ON")

    # ---------- nodes ----------
    def create_node(self, labels: Set[str], props: Dict[str, Any]) -> Node:
        nid = str(uuid.uuid4())
        self.db.execute("INSERT INTO nodes(id,labels,props) VALUES(?,?,?)",
                       (nid, json.dumps(list(labels)), json.dumps(props)))
        self.index.add_node(nid, labels, props)
        return Node(nid, labels, props)

    def get_node(self, nid: str) -> Optional[Node]:
        row = self.db.execute("SELECT labels,props FROM nodes WHERE id=?", (nid,)).fetchone()
        if row:
            return Node(nid, set(json.loads(row[0])), json.loads(row[1]))
        return None

    def delete_node(self, nid: str):
        """Удаление с правильным порядком: сначала индекс, потом связи, потом узел"""
        self.index.drop_node(nid)
        self.db.execute("DELETE FROM rels WHERE start_id=? OR end_id=?", (nid, nid))
        self.db.execute("DELETE FROM nodes WHERE id=?", (nid,))

    def update_node(self, nid: str, new_props: Dict[str, Any]):
        node = self.get_node(nid)
        if not node:
            return
        self.db.execute("UPDATE nodes SET props=? WHERE id=?", (json.dumps(new_props), nid))
        for label in node.labels:
            self._update_index(nid, label, new_props)

    # ---------- rels ----------
    def create_rel(self, start: str, end: str, rel_type: str, props: Dict[str, Any]) -> Relationship:
        rid = str(uuid.uuid4())
        self.db.execute("INSERT INTO rels(id,start_id,end_id,type,props) VALUES(?,?,?,?,?)",
                       (rid, start, end, rel_type, json.dumps(props)))
        return Relationship(rid, start, end, rel_type, props)

    def delete_rel(self, rid: str):
        self.db.execute("DELETE FROM rels WHERE id=?", (rid,))

    def get_rels(self, node_id: str, direction: str = 'both', rel_type: Optional[str] = None) -> List[Relationship]:
        """Получение связей узла"""
        if direction == 'out':
            sql = "SELECT * FROM rels WHERE start_id=?"
            params = (node_id,)
        elif direction == 'in':
            sql = "SELECT * FROM rels WHERE end_id=?"
            params = (node_id,)
        else:
            sql = "SELECT * FROM rels WHERE start_id=? OR end_id=?"
            params = (node_id, node_id)
        
        if rel_type:
            sql += " AND type=?"
            params += (rel_type,)
        
        cur = self.db.execute(sql, params)
        return [Relationship(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in cur]

    # ---------- transactions ----------
    def begin(self):
        self.db.execute("BEGIN")

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    # ---------- index ----------
    def _update_index(self, nid: str, label: str, new_props: dict[str, Any]):
        """Обновляет idx после изменения свойств узла"""
        # Удаляем старые записи для этого узла и этих ключей
        for k in new_props:
            self.db.execute("DELETE FROM idx WHERE node_id=? AND prop_key=?", (nid, k))
            v = new_props[k]
            if v is not None:
                self.db.execute(
                    "INSERT INTO idx(label,prop_key,prop_val,node_id) VALUES(?,?,?,?)",
                    (label, k, str(v), nid))