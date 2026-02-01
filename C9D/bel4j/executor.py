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
                str(item).lower() == 'true' if str(item).lower() in ['true','false'] else
                str(item))
    return item


class Exec(Transformer):
    def __init__(self, graph: Graph):
        super().__init__()
        self.graph = graph
        self.result: list = []
        self.context: dict = {}

    # ========== единый обработчик CREATE ==========
    def create_clause(self, args):
        """CREATE (a)-[:R]->(b) -- всегда создаем новые, без контекста"""
        self.context.clear()
        results = []
        # args[0] - это create_paths (список path_pattern'ов)
        create_patterns = args[0] if args else []
        if not isinstance(create_patterns, list):
            create_patterns = [create_patterns]
            
        for path in create_patterns:
            if isinstance(path, list):
                created = self._create_path(path, use_context=False)
                results.extend(created)
        return results
    
    # ========== обработка шаблонов узлов ==========
    def node_pattern(self, children):
        # Обработка случая, когда identifier отсутствует
        
        var = None
        label = None
        props = {}
        
        for child in children:
            if isinstance(child, str):
            
                if var is None and not child.startswith(':') and '=' not in child:
                    var = child
                elif child != var:
                    label = child
            elif isinstance(child, dict):
                props = child
        
        return {'type': 'node', 'var': var, 'label': label, 'props': props}

    def match_paths(self, children):
        return children

    def create_paths(self, children):
        return children

    def return_items(self, children):
        return children
    
    def bare_rel(self, children):
        """Обрабатывает [:TYPE]"""
        result = {'type': 'rel', 'direction': 'both'}
        for child in children:
            if isinstance(child, dict):
                result.update(child)
        return result

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
        
        # 1. primary_condition
        if expr[0] in op_map:
            op_str, e_ident, prop, val = expr
            if e_ident != ident:
                return pre_nodes if pre_nodes is not None else []

            op_func = op_map[op_str]
            
            # Используем индекс только если есть конкретный label и оператор =
            if pre_nodes is None and op_str == "=" and label is not None:
                ids = self.graph.index.lookup(label, prop, str(val))
                return [self.graph.get_node(i) for i in ids if self.graph.get_node(i)]

            if pre_nodes is None:
                # Если label=None - выбираем ВСЕ узлы, иначе по label
                if label is None:
                    cur = self.graph.db.execute("SELECT id FROM nodes")
                else:
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

        # 2. AND - без изменений
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
                if label is None:
                    cur = self.graph.db.execute("SELECT id FROM nodes")
                else:
                    cur = self.graph.db.execute("SELECT id FROM nodes WHERE json_extract(labels,'$[0]')=?", (label,))
                pre_nodes = [self.graph.get_node(r[0]) for r in cur if self.graph.get_node(r[0])]
            forbidden_ids = {n.id for n in self._filter_nodes(sub, label, ident, pre_nodes)}
            return [n for n in pre_nodes if n.id not in forbidden_ids]
        
        return []
        
    def match_clause(self, args):
        """
        args[0]: match_paths - список path_pattern'ов
        args[1]: condition (если есть WHERE) или return_items
        args[2]: return_items (если есть WHERE)
        """
        match_patterns = args[0] if len(args) > 0 else []
        if not isinstance(match_patterns, list):
            match_patterns = [match_patterns]
        
        where = None
        ret_items = []
        
        if len(args) == 2:
            # Нет WHERE: MATCH ... RETURN ...
            ret_items = args[1] if isinstance(args[1], list) else [args[1]]
        elif len(args) == 3:
            # Есть WHERE: MATCH ... WHERE ... RETURN ...
            where = args[1]
            ret_items = args[2] if isinstance(args[2], list) else [args[2]]
        
        if not match_patterns:
            return []
        
        # Обрабатываем все паттерны MATCH (декартово произведение)
        # Начинаем с первого паттерна
        all_matches = self._match_path(match_patterns[0], where if len(match_patterns) == 1 else None)
        
        # Если паттернов несколько (например MATCH (a), (b)), делаем соединение
        for i in range(1, len(match_patterns)):
            next_pattern = match_patterns[i]
            next_matches = self._match_path(next_pattern, None)
            
            # Декартово произведение
            combined = []
            for m1 in all_matches:
                for m2 in next_matches:
                    # Проверяем, что переменные не конфликтуют (если одна и та же переменная в разных паттернах)
                    conflict = False
                    for key in m1:
                        if key in m2 and m1[key].id != m2[key].id:
                            conflict = True
                            break
                    if not conflict:
                        combined.append({**m1, **m2})
            all_matches = combined
            
            # Применяем WHERE после соединения всех паттернов (если он еще не применен)
            if where and i == len(match_patterns) - 1:
                all_matches = [m for m in all_matches if self._check_where_for_match(m, where)]
        
        # Если был всего один паттерн и есть WHERE, _match_path уже применил фильтр (если мы его туда передали)
        # Но если мы применяли WHERE выше для одного паттерна, он уже отработал
        
        # Формируем результат
        results = []
        for match in all_matches:
            row = {}
            for item in ret_items:
                if '.' in item:
                    var, prop = item.split('.', 1)  # разделяем только по первой точке
                    obj = match.get(var)
                    if isinstance(obj, (Node, Relationship)):
                        row[item] = obj.props.get(prop)
                    else:
                        row[item] = None
                else:
                    obj = match.get(item)
                    if isinstance(obj, (Node, Relationship)):
                        row[item] = obj  # или можно возвращать obj.props если нужно
                    else:
                        row[item] = obj
            results.append(row)
        return results
    def delete_path(self, children):
        """Обрабатывает delete_path: node_pattern или node_pattern rel_pattern node_pattern"""
        elements = [c for c in children if isinstance(c, dict)]
        
        has_rel = any(e.get('type') == 'rel' for e in elements)
        
        if has_rel:
            return {'type': 'path', 'elements': elements}
        else:
            # Только node_pattern
            return elements[0] if elements else {'type': 'node', 'var': None, 'label': None, 'props': {}}
        
    def delete_clause(self, args):
        """DELETE (n), ()-[]-(), [r:TYPE]"""
        items_to_delete = args[0] if args else []
        
        if not isinstance(items_to_delete, list):
            items_to_delete = [items_to_delete]
        
        where = None
        if len(args) > 1 and isinstance(args[1], Tree) and args[1].data == 'condition':
            where = args[1]
        
        deleted_nodes = []
        deleted_rels = []
        
        for item in items_to_delete:
            if not isinstance(item, dict):
                continue
            
            item_type = item.get('type')
            
            if item_type == 'node':
                nodes = self._find_nodes_to_delete(item, where)
                for node in nodes:
                    self._delete_rels_for_node(node.id)
                    self.graph.delete_node(node.id)
                    deleted_nodes.append(node.id)
                    
            elif item_type == 'rel':
                rels = self._find_rels_to_delete(item, where)
                for rel in rels:
                    self.graph.delete_rel(rel.id)
                    deleted_rels.append(rel.id)
                    
            elif item_type == 'path':
                # Путь ()-[]-() - удаляем связь между узлами
                elements = item.get('elements', [])
                if len(elements) >= 3:  # node - rel - node
                    start_node = elements[0]
                    rel = elements[1]
                    end_node = elements[2]
                    
                    # Находим конкретную связь
                    rels = self._find_rels_in_path(start_node, rel, end_node, where)
                    for r in rels:
                        self.graph.delete_rel(r.id)
                        deleted_rels.append(r.id)
        
        return [{
            "deleted_nodes": len(deleted_nodes),
            "deleted_rels": len(deleted_rels),
            "node_ids": deleted_nodes,
            "rel_ids": deleted_rels
        }]
    
    def _find_rels_in_path(self, start_node_spec, rel_spec, end_node_spec, where=None):
        """Находит связи между двумя узлами по спецификации"""
        rel_type = rel_spec.get('rel_type')
        direction = rel_spec.get('direction', 'both')
        
        # Находим стартовые узлы
        start_nodes = self._find_nodes_to_delete(start_node_spec, None)
        end_nodes = self._find_nodes_to_delete(end_node_spec, None)
        
        start_ids = {n.id for n in start_nodes}
        end_ids = {n.id for n in end_nodes}
        
        # Ищем связи
        sql = "SELECT id, start_id, end_id, type, props FROM rels WHERE 1=1"
        params = []
        
        if rel_type:
            sql += " AND type = ?"
            params.append(rel_type)
        
        cur = self.graph.db.execute(sql, params)
        result = []
        
        for row in cur:
            rel = Relationship(row[0], row[1], row[2], row[3], json.loads(row[4]))
            
            # Проверяем направление
            matches_start = rel.start in start_ids and rel.end in end_ids
            matches_end = rel.end in start_ids and rel.start in end_ids
            
            if direction == 'out' and matches_start:
                result.append(rel)
            elif direction == 'in' and matches_end:
                result.append(rel)
            elif direction == 'both' and (matches_start or matches_end):
                result.append(rel)
        
        return result
    def delete_items(self, children):
        """Обрабатывает список элементов для удаления"""
        return children  # children уже список обработанных delete_item

    def delete_item(self, children):
        """Обрабатывает delete_item: узел, путь ()-[]-(), или просто связь [] / -[]-"""
        elements = [c for c in children if isinstance(c, dict)]
        
        # Если всего один элемент и это связь - это bare_rel [:TYPE] или rel_both -[:TYPE]-
        if len(elements) == 1 and elements[0].get('type') == 'rel':
            return elements[0]
        # Если несколько элементов с связью - это путь ()-[]-()
        elif len(elements) > 1 and any(e.get('type') == 'rel' for e in elements):
            return {'type': 'path', 'elements': elements}
        # Если один элемент (узел)
        elif len(elements) == 1:
            return elements[0]
        else:
            return {'type': 'node', 'var': None, 'label': None, 'props': {}}
    
    def _find_nodes_to_delete(self, node_spec, where=None):
        """Находит узлы для удаления"""
        label = node_spec.get('label')
        props = node_spec.get('props', {})
        var = node_spec.get('var')
        
        # Если есть переменная в контексте
        if var and var in self.context:
            node = self.context[var]
            if where and not self._check_where_for_match({var: node}, where):
                return []
            return [node]
        
        # Ищем по label/props
        nodes = self._find_start_nodes(node_spec)
        
        # Применяем WHERE если есть
        if where:
            filtered = []
            for node in nodes:
                match = {var or 'n': node}
                if self._check_where_for_match(match, where):
                    filtered.append(node)
            nodes = filtered
        
        return nodes

    def _find_rels_to_delete(self, rel_spec, where=None):
        """Находит связи для удаления"""
        rel_type = rel_spec.get('rel_type')
        props = rel_spec.get('props', {})
        var = rel_spec.get('var')
        
        # Если есть переменная в контексте
        if var and var in self.context:
            rel = self.context[var]
            if isinstance(rel, Relationship):
                if where:
                    # Для связей WHERE проверяем сложнее, пока пропускаем
                    pass
                return [rel]
            return []
        
        # Ищем по типу
        sql = "SELECT id, start_id, end_id, type, props FROM rels WHERE 1=1"
        params = []
        
        if rel_type:
            sql += " AND type = ?"
            params.append(rel_type)
        
        cur = self.graph.db.execute(sql, params)
        result = []
        for row in cur:
            rel = Relationship(row[0], row[1], row[2], row[3], json.loads(row[4]))
            if props:
                if all(str(rel.props.get(k)) == str(v) for k, v in props.items()):
                    result.append(rel)
            else:
                result.append(rel)
        return result
    
    def _delete_rels_for_node(self, node_id):
        """Удаляет все связи узла (каскадно)"""
        # Находим все связи где узел start или end
        cur = self.graph.db.execute(
            "SELECT id FROM rels WHERE start_id = ? OR end_id = ?", 
            (node_id, node_id)
        )
        for row in cur:
            self.graph.delete_rel(row[0])
            
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
    
    def rel_out(self, children):
        result = {'type': 'rel', 'direction': 'out'}
        for child in children:
            if isinstance(child, dict):
                result.update(child)
        return result

    def rel_in(self, children):
        result = {'type': 'rel', 'direction': 'in'}
        for child in children:
            if isinstance(child, dict):
                result.update(child)
        return result

    def rel_both(self, children):
        result = {'type': 'rel', 'direction': 'both'}
        for child in children:
            if isinstance(child, dict):
                result.update(child)
        return result

    def rel_pattern(self, children):
        # Собираем строку из всех токенов для анализа
        tokens_str = ''
        for child in children:
            if isinstance(child, Token):
                tokens_str += str(child.value)  # Используем .value, а не str()
        
        
        # Определяем направление
        has_in = '<-' in tokens_str
        has_out = '->' in tokens_str
        
        if has_in and not has_out:
            direction = 'in'      # <-[]-
        elif has_out and not has_in:
            direction = 'out'     # -[]->
        else:
            direction = 'both'    # -[]- или <-[]->
        
        result = {'type': 'rel', 'direction': direction}
        
        # Добавляем информацию из rel_info (var, type, props)
        for child in children:
            if isinstance(child, dict):
                result.update(child)
        
        return result
        
    def rel_info(self, children):
        """Парсит [r:TYPE {props}] - исправлено для надежного извлечения props"""
        result = {}
        for child in children:
            if isinstance(child, str):
                val = child
                if val and val[0].islower():
                    result['var'] = val
                else:
                    result['rel_type'] = val
            elif isinstance(child, Token):
                val = str(child)
                if val and val[0].islower():
                    result['var'] = val
                else:
                    result['rel_type'] = val
            elif isinstance(child, Tree):
                # Если Tree не преобразовался в dict автоматически (на всякий случай)
                if child.data == 'props':
                    # Преобразуем вручную
                    props_dict = {}
                    for prop_item in child.children:
                        if isinstance(prop_item, (tuple, list)) and len(prop_item) == 2:
                            k, v = prop_item
                            props_dict[str(k)] = v
                        elif isinstance(prop_item, Tree) and prop_item.data == 'prop_pair':
                            k, v = prop_item.children
                            props_dict[str(_unwrap(k))] = _unwrap(v)
                    result['props'] = props_dict
                elif child.data == 'rel_type' and child.children:
                    result['rel_type'] = str(child.children[0])
            elif isinstance(child, dict):
                # Это результат метода props - используем как есть
                result['props'] = child
        return result
    
    def _create_path(self, path_elements, use_context=False):
        """
        Создает цепочку узел-связь-узел.
        Если use_context=True и переменная есть в self.context - используем существующий узел.
        """
        created = []
        nodes = []  # [(var_name, node_obj), ...]
        pending_rel = None
        
        i = 0
        while i < len(path_elements):
            elem = path_elements[i]
            
            if elem['type'] == 'node':
                var = elem.get('var')
                
                # Проверяем, можем ли использовать существующий узел из контекста MATCH
                if use_context and var and var in self.context:
                    # Используем существующий узел (не создаем новый)
                    existing_node = self.context[var]
                    nodes.append((var, existing_node))
                    # Проверка совместимости label/props если они указаны в CREATE
                    if elem.get('label') and elem['label'] not in existing_node.labels:
                        raise ValueError(f"Node {var} exists with labels {existing_node.labels}, expected {elem['label']}")
                else:
                    # Создаем новый узел
                    labels = {elem['label']} if elem.get('label') else set()
                    node = self.graph.create_node(labels, elem.get('props', {}))
                    nodes.append((var, node))
                    created.append(node)
                    # Если есть переменная, сохраняем в контекст для дальнейшего использования в этом же пути
                    if var:
                        self.context[var] = node
                
                # Обработка отложенной связи
                if pending_rel and len(nodes) >= 2:
                    prev_node = nodes[-2][1]
                    curr_node = nodes[-1][1]
                    
                    direction = pending_rel.get('direction', 'out')
                    
                    if direction == 'in':
                        start_id = curr_node.id
                        end_id = prev_node.id
                    else:
                        start_id = prev_node.id
                        end_id = curr_node.id
                    
                    rel = self.graph.create_rel(
                        start_id,
                        end_id,
                        pending_rel.get('rel_type', 'RELATED'),
                        pending_rel.get('props', {})
                    )
                    created.append(rel)
                    pending_rel = None
                    
            elif elem['type'] == 'rel':
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
        
        if label and props:
            first_prop = next(iter(props))
            first_val = str(props[first_prop])
            ids = self.graph.index.lookup(label, first_prop, first_val)
            
            if ids:
                result = []
                for node_id in ids:
                    node = self.graph.get_node(node_id)
                    if node:
                        if all(str(node.props.get(k)) == str(v) for k, v in props.items()):
                            result.append(node)
                if result:
                    return result
            # КРИТИЧНО: Если не нашли по индексу или после фильтрации пусто - возвращаем []
            # НЕ сканируем все узлы, т.к. мы искали конкретный узел с конкретными props
            return []
        
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
            if label is None:
                cur = self.graph.db.execute("SELECT id FROM nodes")
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
    
    # ========== MATCH ... CREATE ... ==========
    def match_create_clause(self, args):
        """
        args[0]: match_paths - список паттернов для поиска
        args[1]: condition (если есть) или create_paths
        args[2]: create_paths (если есть condition)
        """
        match_patterns = args[0] if len(args) > 0 else []
        if not isinstance(match_patterns, list):
            match_patterns = [match_patterns]
        
        where = None
        create_patterns = []
        
        if len(args) == 2:
            # Нет WHERE
            create_patterns = args[1] if isinstance(args[1], list) else [args[1]]
        elif len(args) == 3:
            # Есть WHERE
            where = args[1]
            create_patterns = args[2] if isinstance(args[2], list) else [args[2]]
        
        if not match_patterns or not create_patterns:
            return []
        
        # Находим все совпадения для MATCH (аналогично match_clause)
        all_matches = self._match_path(match_patterns[0], where if len(match_patterns) == 1 else None)
        
        # Обрабатываем дополнительные паттерны MATCH (если есть)
        for i in range(1, len(match_patterns)):
            next_pattern = match_patterns[i]
            next_matches = self._match_path(next_pattern, None)
            
            combined = []
            for m1 in all_matches:
                for m2 in next_matches:
                    conflict = False
                    for key in m1:
                        if key in m2 and m1[key].id != m2[key].id:
                            conflict = True
                            break
                    if not conflict:
                        combined.append({**m1, **m2})
            all_matches = combined
            
            if where and i == len(match_patterns) - 1:
                all_matches = [m for m in all_matches if self._check_where_for_match(m, where)]
        
        if not all_matches:
            return []
        
        all_created = []
        
        # Для каждой строки результата MATCH выполняем CREATE
        for match in all_matches:
            self.context = match.copy()  # Загружаем переменные из MATCH
            
            for path in create_patterns:
                created = self._create_path(path, use_context=True)
                all_created.extend(created)
            
            self.context.clear()
        
        return all_created
    
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