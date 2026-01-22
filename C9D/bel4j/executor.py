from __future__ import annotations
try:
    from .core import Graph, Node, Relationship
    from . import parser
except ImportError:
    from core import Graph, Node, Relationship
    import parser
from lark import Transformer, Tree, Token
import json

def _unwrap(item):
    """Tree / Token -> python-объект рекурсивно."""
    if isinstance(item, Tree):
        if item.data == 'props':
            return dict(_unwrap(ch) for ch in item.children)
        if item.data == 'prop_pair':
            k, v = item.children
            return str(_unwrap(k)), _unwrap(v)
        return [_unwrap(ch) for ch in item.children]
    if isinstance(item, Token):
        return (str(item).strip('"') if item.type == 'STRING' else
                float(item)          if item.type == 'NUMBER' else
                str(item))
    return item


class Exec(Transformer):
    def __init__(self, graph: Graph):
        super().__init__()
        self.graph = graph
        self.result: list = []

    # ========== единый обработчик CREATE ==========
    def create_clause(self, children):
        # children — список кортежей (ident_list, label_list, props_dict)
        result = []
        for ident_list, label_list, props_dict in children:
            label = label_list[0]
            node = self.graph.create_node({label}, props_dict or {})
            result.append(node)
        return result
    
    # ========== обработка шаблонов узлов ==========
    def node_pattern(self, children):
        # children = [identifier, label, props(optional)]
        identifier = str(children[0])  # identifier
        label = str(children[1])       # label
        props = children[2] if len(children) > 2 else {}  # props or empty dict
        return [identifier], [label], props

    def props(self, children):
        # Children are prop_pairs
        result = {}
        for pair in children:
            if isinstance(pair, tuple) and len(pair) == 2:
                key, value = pair
                result[key] = value
            else:
                # Handle case where children are processed differently
                unwrapped = _unwrap(pair)
                if isinstance(unwrapped, dict):
                    result.update(unwrapped)
        return result

    def prop_pair(self, children):
        key, value = children
        return str(key), _unwrap(value)

    # Token methods to properly unwrap values
    def identifier(self, children):
        return str(children[0])

    def label(self, children):
        return str(children[0])

    def prop_name(self, children):
        return str(children[0])

    def literal(self, children):
        return _unwrap(children[0])
    
    def query(self, children):
        # Return the result of the clause (first child)
        return children[0] if children else []

    def condition(self, children):
        # просто отдаём дерево дальше
        return Tree('condition', children)

    def primary_condition(self, children):
        # всегда плоский кортеж
        ident, prop, val = children
        return ('=', str(ident), str(prop), _unwrap(val))
    
    def _flatten_expr(self, expr):
        """Tree → плоский кортеж ('=', 'n', 'name', 'Bob1') или ('AND', left, right)."""
        # 1. один ребёнок – углубляемся
        if isinstance(expr, Tree) and len(expr.children) == 1:
            return self._flatten_expr(expr.children[0])

        # 2. два ребёнка – «плющ» + рекурсия
        if isinstance(expr, Tree) and len(expr.children) == 2:
            op = 'OR' if expr.data == 'or_expr' else 'AND'
            left  = self._flatten_expr(expr.children[0])
            right = self._flatten_expr(expr.children[1])
            return (op, left, right)

        # 3. лист – primary_condition
        if isinstance(expr, Tree) and expr.data == 'primary_condition':
            ident_tok, prop_tok, val_tok = expr.children
            return ('=', str(ident_tok), str(prop_tok), _unwrap(val_tok))

        # 4. not_expr – убрать один уровень
        if isinstance(expr, Tree) and expr.data == 'not_expr' and len(expr.children) == 1:
            return self._flatten_expr(expr.children[0])

        # 5. всё остальное – уже плоско
        return expr
    
    def _filter_nodes(self, expr, label, ident, pre_nodes=None):
        # 0. рекурсивно раскрываем Tree до плоского выражения
        # print(len(expr.children), expr.data)
        while isinstance(expr, Tree):
            if expr.data == 'condition' and len(expr.children) == 1:
                expr = expr.children[0]
            elif expr.data == 'condition' and len(expr.children) == 3:
                op_tok, left_tree, right_tree = expr.children
                expr = (str(op_tok), left_tree, right_tree)
            elif expr.data == 'primary_condition':
                ident_tok, prop_tok, val_tok = expr.children
                expr = ('=', str(ident_tok), str(prop_tok), _unwrap(val_tok))
            else:
                expr = expr.children[0] if expr.children else expr
        # print(expr)
        # 1. (=, ident, prop, val)
        if expr[0] == '=':
            _, e_ident, prop, val = expr
            if e_ident != ident:
                return pre_nodes if pre_nodes is not None else []
            if pre_nodes is None:
                ids = self.graph.index.lookup(label, prop, str(val))
                # print(ids)
                return [self.graph.get_node(i) for i in ids if self.graph.get_node(i)]
            else:
                result = [n for n in pre_nodes if prop in n.props and n.props[prop] == val]
                return result

        # 2. AND
        if expr[0] == 'AND':
            left, right = expr[1], expr[2]
            interim = self._filter_nodes(left, label, ident, pre_nodes)
            result  = self._filter_nodes(right, label, ident, interim)
            return result

        # 3. OR
        if expr[0] == 'OR':
            left, right = expr[1], expr[2]
            left_ids  = [n.id for n in self._filter_nodes(left, label, ident, pre_nodes)]
            right_ids = [n.id for n in self._filter_nodes(right, label, ident, pre_nodes)]
            merged_ids = set(left_ids) | set(right_ids)
            # возвращаем Node-ы по id
            return [n for n in self.graph.db.execute(
                "SELECT id, labels, props FROM nodes WHERE id IN ({})".format(','.join('?'*len(merged_ids))),
                list(merged_ids))
            ] if merged_ids else []
        
        
        # 4. NOT
        if expr[0] == 'NOT':
            sub = expr[1]
            if pre_nodes is None:
                cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
                pre_nodes = [self.graph.get_node(row[0]) for row in cur]
                pre_nodes = [n for n in pre_nodes if n is not None]
            forbidden = set(self._filter_nodes(sub, label, ident, pre_nodes))
            return [n for n in pre_nodes if n not in forbidden]
        
    def match_clause(self, args):
        node_spec, *rest = args
        ident_list, label_list, _props = node_spec
        label = label_list[0]
        where = None
        ret_ids = []
        for r in rest:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
            elif isinstance(r, list):
                ret_ids = r
        nodes: list[Node] = []
        if where:
            # print("where --> ", where)
            flat_expr = self._flatten_expr(where)
            # print("flat_expr --> ", flat_expr)
            nodes = self._filter_nodes(flat_expr, label, ident_list[0], None)
        else:
            cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
            nodes = [self.graph.get_node(row[0]) for row in cur]
            nodes = [n for n in nodes if n is not None]

        returned = []
        for n in nodes:
            returned.append({ident_list[0]: n})
        return returned
    
    def delete_clause(self, _):
        return []
    
    def set_clause(self, args):
        # разбор уже есть, получаем node_id, new_props, label
        node_spec, *rest = args
        ident_list, label_list, _props = node_spec
        label = label_list[0]
        where = None
        set_items = []
        for r in rest:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
            elif isinstance(r, list):
                set_items = r

        # находим узел
        flat_where = self._flatten_expr(where) if where else None
        nodes = self._filter_nodes(flat_where, label, ident_list[0], None) if where else []
        if not nodes:
            return []

        # применяем SET к первому найденному (упрощённо)
        node = nodes[0]
        new_props = {}
        for item in set_items:          # item = ('=', 'n', 'age', 30)
            _, e_ident, prop, val = item
            if e_ident == ident_list[0]:
                new_props[prop] = val

        # обновляем SQLite
        self.graph.db.execute("UPDATE nodes SET props=? WHERE id=?",
                            (json.dumps({**node.props, **new_props}), node.id))
        # обновляем индекс
        self.graph._update_index(node.id, label, new_props)
        # обновляем объект в памяти
        node.props.update(new_props)
        return [node]
    def return_item(self, children):
        return children[0] if children else None
    def set_item(self, children):
        return children
    

def execute(graph: Graph, query: str):
    tree = parser.parser.parse(query)
    result = Exec(graph).transform(tree)
    flat = []
    for item in result:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return flat