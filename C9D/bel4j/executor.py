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
        """CREATE (a)-[:R]->(b) -- children содержит path_pattern'ы"""
        results = []
        for path in children:
            created = self._create_path(path)
            results.extend(created)
        return results
    
    # ========== обработка шаблонов узлов ==========
    def node_pattern(self, children):
        var = str(children[0])
        label = str(children[1]) if len(children) > 1 else 'Node'
        props = children[2] if len(children) > 2 and isinstance(children[2], dict) else {}
        
        return {'type': 'node', 'var': var, 'label': label, 'props': props}

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

    def _flatten_expr(self, expr):
        """Tree → плоский кортеж ('=', 'n', 'name', 'Bob1') | ('AND',L,R) | ('OR',L,R) ."""
        if isinstance(expr, tuple):
            return expr
        if (isinstance(expr, Tree) and expr.data == 'primary_condition' and len(expr.children) == 2 and isinstance(expr.children[0], Token) and expr.children[0].type == 'NOT'):
            sub = self._flatten_expr(expr.children[1])
            return ('NOT', sub)
        
        # 1. бинарные операции: OR / AND
        if isinstance(expr, Tree) and len(expr.children) == 2:
            op = 'OR' if expr.data == 'or_expr' else 'AND'
            left = self._flatten_expr(expr.children[0])
            right = self._flatten_expr(expr.children[1])
            return (op, left, right)

        # 2. один ребёнок – спускаемся (скобки / обёртки)
        if isinstance(expr, Tree) and len(expr.children) == 1:
            return self._flatten_expr(expr.children[0])

        # 3. primary_condition – раскрываем вручную
        if isinstance(expr, Tree) and expr.data == 'primary_condition':
            # print('[CHILD]', expr.children)
            ident_tok, prop_tok, op_tok, val_tok = expr.children
            op_token = op_tok.children[0]  # Tree → Token
            return (str(op_token),
                    str(ident_tok),
                    str(prop_tok),
                    _unwrap(val_tok))

        return expr
    
    def _filter_nodes(self, expr, label, ident, pre_nodes=None):
        import operator
        op_map = {'=': operator.eq, '!=': operator.ne,
                '>': operator.gt, '>=': operator.ge,
                '<': operator.lt, '<=': operator.le}
        
        # print("[DEBUG]", expr)
        # 1. primary_condition
        if expr[0] in op_map:
            op_str, e_ident, prop, val = expr
            if e_ident != ident:
                return pre_nodes if pre_nodes is not None else []

            op_func = op_map[op_str]
            if pre_nodes is None and op_str == "=":
                ids = self.graph.index.lookup(label, prop, str(val))
                return [self.graph.get_node(i) for i in ids if self.graph.get_node(i)]

            if pre_nodes is None:
                cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
                pre_nodes = [self.graph.get_node(r[0]) for r in cur if self.graph.get_node(r[0])]

            result = []
            for n in pre_nodes:
                if prop in n.props:
                    try:
                        node_val = float(n.props[prop])
                        comp_val = float(val)
                    except (ValueError, TypeError):
                        node_val = str(n.props[prop])
                        comp_val = str(val)
                    if op_func(node_val, comp_val):
                        result.append(n)
            return result

        # 2. AND
        if expr[0] == 'AND':
            left, right = expr[1], expr[2]
            interim = self._filter_nodes(left, label, ident, pre_nodes)
            return self._filter_nodes(right, label, ident, interim)

        # 3. OR
        if expr[0] == 'OR':
            left, right = expr[1], expr[2]
            left_ids  = {n.id for n in self._filter_nodes(left, label, ident, pre_nodes)}
            right_ids = {n.id for n in self._filter_nodes(right, label, ident, pre_nodes)}
            merged = left_ids | right_ids
            if not merged:
                return []
            cur = self.graph.db.execute(
                f"SELECT id, labels, props FROM nodes WHERE id IN ({','.join('?'*len(merged))})",
                list(merged))
            return [Node(id=r[0], labels=json.loads(r[1]), props=json.loads(r[2])) for r in cur]
        # 4. NOT
        if expr[0] == 'NOT':
            sub = expr[1]
            if pre_nodes is None:
                cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
                pre_nodes = [self.graph.get_node(r[0]) for r in cur if self.graph.get_node(r[0])]
            forbidden_ids = {n.id for n in self._filter_nodes(sub, label, ident, pre_nodes)}
            return [n for n in pre_nodes if n.id not in forbidden_ids]
        return []
        
    def match_clause(self, args):
        path = args[0]
        where = None
        ret_items = []  # теперь это список строк!
        
        for r in args[1:]:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
            elif isinstance(r, str):  # return_item теперь возвращает строку
                ret_items.append(r)
            elif isinstance(r, list):  # на случай если несколько return_item
                ret_items.extend([x for x in r if isinstance(x, str)])
        
        # Если нет return_items, возвращаем все переменные из пути
        if not ret_items and path:
            ret_items = [elem.get('var') for elem in path if elem.get('var')]
        
        # Ищем пути
        matches = self._match_path(path, where)
        
        # Формируем результат
        results = []
        for match in matches:
            row = {}
            for item in ret_items:
                if '.' in item:
                    var, prop = item.split('.')
                    obj = match.get(var)
                    if isinstance(obj, (Node, Relationship)):
                        row[item] = obj.props.get(prop)
                    else:
                        row[item] = None
                else:
                    obj = match.get(item)
                    row[item] = obj
            results.append(row)
        return results
        
    def delete_clause(self, args):
        # args: [node_spec, where_condition?]
        node_spec = args[0]  # dict: {'type': 'node', 'var': 'p', 'label': 'Person', ...}
        label = node_spec['label']
        ident = node_spec['var']
        
        where = None
        for r in args[1:]:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
                break
        
        # Находим узлы для удаления
        if where:
            flat_expr = self._flatten_expr(where)
            nodes = self._filter_nodes(flat_expr, label, ident, None)
        else:
            # Если нет WHERE — удаляем ВСЕ узлы с таким label (опасно!)
            cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
            nodes = [self.graph.get_node(row[0]) for row in cur]
        
        deleted_count = 0
        for node in nodes:
            self.graph.delete_node(node.id)  # Каскадное удаление связей уже есть в core.py
            deleted_count += 1
        
        return [{"deleted": deleted_count, "nodes": [n.id for n in nodes]}]
    
    def set_clause(self, args):
        """MATCH ... SET ... - работает с новым форматом dict"""
        node_spec = args[0]  # dict: {'type': 'node', 'var': 'n', 'label': 'Person', ...}
        label = node_spec['label']
        ident = node_spec['var']
        
        where = None
        set_items = []
        for r in args[1:]:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
            elif isinstance(r, list):  # set_items приходят списком
                set_items = r

        # Находим узлы
        flat_where = self._flatten_expr(where) if where else None
        nodes = self._filter_nodes(flat_where, label, ident, None) if where else []
        
        if not nodes:
            # Если нет WHERE, берем все узлы с этим label
            cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
            nodes = [self.graph.get_node(row[0]) for row in cur if self.graph.get_node(row[0])]

        if not nodes:
            return []

        # Применяем SET к найденным узлам
        updated = []
        for node in nodes:
            new_props = {}
            for item in set_items:  # item = ('=', 'n', 'age', 30)
                _, e_ident, prop, val = item
                if e_ident == ident:
                    new_props[prop] = val
            
            if new_props:
                # Обновляем SQLite
                merged_props = {**node.props, **new_props}
                self.graph.db.execute("UPDATE nodes SET props=? WHERE id=?",
                                    (json.dumps(merged_props), node.id))
                # Обновляем индекс
                self.graph._update_index(node.id, label, new_props)
                # Обновляем объект в памяти
                node.props.update(new_props)
                updated.append(node)
        
        return updated
    
    def return_item(self, children):
        """Возвращает строку 'n' или 'n.name'"""
        if len(children) == 1:
            return str(children[0])
        elif len(children) == 2:
            return f"{children[0]}.{children[1]}"  # n.name
        return str(children[0])

    def set_item(self, children):
        """identifier "." prop_name "=" literal -> ('=', 'n', 'age', 30)"""
        if len(children) >= 3:
            var = str(children[0])
            prop = str(children[1])
            val = children[2]
            result = ('=', var, prop, val)
            return result
        # Fallback - не должно случиться
        return ('=', '', '', 0)

    
    def path_pattern(self, children):
        """Всегда возвращает список элементов пути"""   
        if not isinstance(children, list):
            children = [children]
        return children

    def rel_pattern(self, children):
        result = {'type': 'rel', 'direction': 'out'}
        for child in children:
            if isinstance(child, Token):
                if child.value == '<-': result['direction'] = 'in'
                elif child.value == '->': result['direction'] = 'out'
            elif isinstance(child, dict):
                result.update(child)
        return result
    
    def rel_info(self, children):
        """Парсит [r:TYPE {props}] - исправлено для различения var и type"""
        result = {}
        for child in children:
            if isinstance(child, str):  # <-- ИЗМЕНЕНИЕ: проверяем str первым!
                # Это уже строка (от processed Token)
                val = child
                if val[0].islower() if val else False:  # переменные обычно с маленькой
                    result['var'] = val
                else:
                    result['rel_type'] = val
            elif isinstance(child, Token):
                val = str(child)
                if val[0].islower() if val else False:
                    result['var'] = val
                else:
                    result['rel_type'] = val
            elif isinstance(child, Tree):
                if child.data == 'rel_type' and child.children:
                    result['rel_type'] = str(child.children[0])
            elif isinstance(child, dict):
                result['props'] = child
        return result

    def _create_path(self, path_elements):
        """Создает цепочку: узел-связь-узел с учетом направления (->, <-, --)"""
        created = []
        nodes = []  # [(var_name, node_obj), ...]
        pending_rel = None  # Отложенная связь с направлением
        
        i = 0
        while i < len(path_elements):
            elem = path_elements[i]
            
            if elem['type'] == 'node':
                # Создаем узел
                node = self.graph.create_node(
                    {elem['label']}, 
                    elem.get('props', {})
                )
                nodes.append((elem.get('var'), node))
                created.append(node)
                
                # Если есть отложенная связь и теперь узлов достаточно - создаем её
                if pending_rel and len(nodes) >= 2:
                    prev_node = nodes[-2][1]  # предыдущий узел (a)
                    curr_node = nodes[-1][1]  # текущий узел (b)
                    
                    # Определяем направление связи
                    direction = pending_rel.get('direction', 'out')
                    
                    if direction == 'in':
                        # Входящая связь: (a)<-[:TYPE]-(b) означает b->a
                        # start = b (текущий), end = a (предыдущий)
                        start_id = curr_node.id
                        end_id = prev_node.id
                    else:
                        # Исходящая или ненаправленная: (a)-[:TYPE]->(b)
                        # start = a (предыдущий), end = b (текущий)
                        start_id = prev_node.id
                        end_id = curr_node.id
                    
                    rel = self.graph.create_rel(
                        start_id,
                        end_id,
                        pending_rel.get('rel_type', 'RELATED'),
                        pending_rel.get('props', {})
                    )
                    created.append(rel)
                    pending_rel = None  # Сбрасываем отложенную связь
                    
            elif elem['type'] == 'rel':
                # Откладываем связь до создания следующего узла
                pending_rel = elem
                    
            i += 1
        
        return created

    def _match_path(self, path_elements, where):
        """Ищет все пути, соответствующие паттерну (a)-[r]->(b)"""
        if not path_elements:
            return []
        
        # Начинаем с первого узла
        first_elem = path_elements[0]
        start_nodes = self._find_start_nodes(first_elem)
        
        matches = []
        for node in start_nodes:
            initial_match = {first_elem.get('var', 'n'): node}
            self._traverse_path(0, path_elements, initial_match, where, matches)
        return matches
    
    def _traverse_path(self, pos, path, current_match, where, results):
        """Рекурсивный обход - исправлены границы-check"""
        if pos >= len(path):
            if self._check_where_for_match(current_match, where):
                results.append(current_match.copy())
            return
        
        current_elem = path[pos]
        
        # Если это последний элемент (узел) и мы дошли до конца
        if pos == len(path) - 1 and current_elem.get('type') == 'node':
            if self._check_where_for_match(current_match, where):
                results.append(current_match.copy())
            return
        
        if pos + 1 >= len(path):
            return
        
        next_elem = path[pos + 1]
        
        if current_elem.get('type') == 'node' and next_elem.get('type') == 'rel':
            node_var = current_elem.get('var')
            if node_var not in current_match:
                return
                
            current_node = current_match[node_var]
            
            direction = next_elem.get('direction', 'out')
            rel_type = next_elem.get('rel_type')
            try:
                rels = self.graph.get_rels(current_node.id, direction, rel_type)
            except Exception as e:
                print(f"[DEBUG] ERROR: {e}")
                return

            for rel in rels:
                # Определяем соседний узел
                neighbor_id = None
                if direction == 'out':
                    neighbor_id = rel.end
                elif direction == 'in':
                    neighbor_id = rel.start
                else:  # both
                    neighbor_id = rel.end if rel.start == current_node.id else rel.start
                
                neighbor = self.graph.get_node(neighbor_id)
                if not neighbor:
                    continue
                
                # Проверяем следующий узел в паттерне (если есть)
                next_node_var = None
                if pos + 2 < len(path):
                    next_node_spec = path[pos + 2]
                    if next_node_spec.get('type') == 'node':
                        if next_node_spec.get('label') and next_node_spec['label'] not in neighbor.labels:
                            continue
                        next_node_var = next_node_spec.get('var')
                
                # Добавляем в матч
                rel_var = next_elem.get('var')
                if rel_var:
                    current_match[rel_var] = rel
                
                if next_node_var:
                    current_match[next_node_var] = neighbor
                
                # Рекурсия
                self._traverse_path(pos + 2, path, current_match, where, results)
                
                # Бэктрекинг
                if rel_var and rel_var in current_match:
                    del current_match[rel_var]
                if next_node_var and next_node_var in current_match:
                    del current_match[next_node_var]
                    
    def _find_start_nodes(self, node_spec):
        """Находит стартовые узлы по label/props"""
        label = node_spec.get('label')
        props = node_spec.get('props', {})
        
        # Используем индекс если есть конкретное свойство
        if label and props:
            for k, v in props.items():
                ids = self.graph.index.lookup(label, k, str(v))
                if ids:
                    return [self.graph.get_node(i) for i in ids if self.graph.get_node(i)]
        
        # Иначе сканируем по label
        if label:
            cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
        else:
            cur = self.graph.db.execute("SELECT id FROM nodes")
        
        return [self.graph.get_node(row[0]) for row in cur if self.graph.get_node(row[0])]
    def _check_where_for_match(self, match, where):
        """Проверяет WHERE для найденного пути"""
        if not where:
            return True
        flat = self._flatten_expr(where)
        return self._eval_condition(flat, match)  # Нужно создать _eval_condition
    
    def _eval_condition(self, expr, match):
        """Вычисляет условие WHERE для найденного пути"""
        if not isinstance(expr, tuple):
            return False
            
        # Логические операторы
        if expr[0] == 'AND':
            return self._eval_condition(expr[1], match) and self._eval_condition(expr[2], match)
        if expr[0] == 'OR':
            return self._eval_condition(expr[1], match) or self._eval_condition(expr[2], match)
        if expr[0] == 'NOT':
            return not self._eval_condition(expr[1], match)
        
        # Операторы сравнения
        op_map = {
            '=': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '>': lambda a, b: float(a) > float(b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else False,
            '>=': lambda a, b: float(a) >= float(b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else False,
            '<': lambda a, b: float(a) < float(b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else False,
            '<=': lambda a, b: float(a) <= float(b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else False,
        }
        
        if expr[0] in op_map:
            op, var, prop, val = expr
            if var not in match:
                return False
            
            obj = match[var]
            actual_val = None
            if isinstance(obj, Node):
                actual_val = obj.props.get(prop)
            elif isinstance(obj, Relationship):
                actual_val = obj.props.get(prop)
            
            try:
                return op_map[op](actual_val, val)
            except (ValueError, TypeError):
                # Если не получилось сравнить как числа, сравниваем как строки
                return str(actual_val) == str(val) if op == '=' else False
        return False
    
    def update_clause(self, args):
        node_spec = args[0]
        label = node_spec['label']
        ident = node_spec['var']
        
        where = None
        set_items = []
        
        # Собираем все кортежи из args (пропускаем node_spec и condition)
        for r in args[1:]:
            if isinstance(r, Tree) and r.data == 'condition':
                where = r
            elif isinstance(r, tuple) and len(r) == 4:  # ('=', 'p', 'age', 31.0)
                set_items.append(r)
        
        # Находим узлы для обновления
        if where:
            flat_where = self._flatten_expr(where)
            nodes = self._filter_nodes(flat_where, label, ident, None)
        else:
            # Без WHERE - обновляем все узлы с этим label
            cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
            nodes = [self.graph.get_node(row[0]) for row in cur if self.graph.get_node(row[0])]
        
        if not nodes:
            return []
        
        # Применяем UPDATE
        updated = []
        for node in nodes:
            new_props = {}
            for item in set_items:  # item = ('=', 'n', 'age', 30)
                _, e_ident, prop, val = item
                if e_ident == ident:
                    new_props[prop] = val
            
            if new_props:
                # Обновляем SQLite
                merged_props = {**node.props, **new_props}
                self.graph.db.execute("UPDATE nodes SET props=? WHERE id=?",
                                    (json.dumps(merged_props), node.id))
                # Обновляем индекс
                self.graph._update_index(node.id, label, new_props)
                node.props.update(new_props)
                updated.append(node)
        
        return [{"updated": len(updated), "nodes": [n.id for n in updated]}]

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