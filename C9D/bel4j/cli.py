import cmd, textwrap
from .manager import Manager

class Bel4jCLI(cmd.Cmd):
    prompt = "bel4j> "

    def __init__(self):
        super().__init__()
        self.graph = None          # текущая открытая база
        self.db_name = None
        self._welcome()

    # ---------- приветствие ----------
    def _welcome(self):
        dbs = Manager.list_dbs()
        print(textwrap.dedent(f"""
        Добро пожаловать в Bel4j!
        Существующие базы: {', '.join(dbs) if dbs else 'нет'}
        Команды:
          CREATEDB <name>  — создать новую базу
          USE <name>       — подключиться к базе
          DROPDB <name>    — удалить базу
          LIST             — показать список баз
          EXIT             — выход
        """))

    # ---------- команды ----------
    def do_CREATEDB(self, arg):
        """CREATEDB имя_базы"""
        try:
            self.graph = Manager.create(arg.strip())
            self.db_name = arg.strip()
            self.prompt = f"bel4j:{self.db_name}> "
            print(f"База '{self.db_name}' создана и открыта.")
        except Exception as e:
            print("Ошибка:", e)

    def do_USE(self, arg):
        """USE имя_базы"""
        try:
            self.graph = Manager.open(arg.strip())
            self.db_name = arg.strip()
            self.prompt = f"bel4j:{self.db_name}> "
            print(f"Подключены к '{self.db_name}'.")
        except Exception as e:
            print("Ошибка:", e)

    def do_LIST(self, _):
        """Показать список баз"""
        dbs = Manager.list_dbs()
        print("Доступные базы:", ", ".join(dbs) if dbs else "нет")

    # ---------- выполнение Cypher ----------
    def default(self, line):
        if line.strip().upper() in ('EXIT', 'QUIT'):
            return self.do_exit(line)
            
        if self.graph is None:
            print("Сначала создайте или выберите базу командой CREATEDB или USE")
            return
        if self.graph is None:
            print("Сначала создайте или выберите базу командой CREATEDB или USE")
            return
        try:
            from .executor import execute
            rows = execute(self.graph, line)
            for r in rows:
                print(r)
        except Exception as e:
            print("Error:", e)

    def do_exit(self, _):
        return True
    
    def do_MIGRATE(self, _):
        import json
        """Перестраивает индекс по всем существующим узлам."""
        if not self.graph:
            print("База не открыта"); return
        cur = self.graph.db.execute("SELECT id, labels, props FROM nodes")
        for nid, lbl_json, prp_json in cur:
            props = json.loads(prp_json)
            labels = json.loads(lbl_json)
            label = labels[0] if labels else 'Unknown'
            for k, v in props.items():
                if v is not None:
                    self.graph.db.execute(
                        "INSERT OR IGNORE INTO idx(label,prop_key,prop_val,node_id) VALUES(?,?,?,?)",
                        (label, k, str(v), nid))
        print("Индекс перестроен.")

    def do_DROPDB(self, arg):
        """DROPDB имя_базы - удалить базу данных"""
        name = arg.strip()
        if not name:
            print("Ошибка: укажите имя базы")
            return
        
        try:
            # Проверяем, не открыта ли эта база сейчас
            if self.db_name == name:
                # Закрываем соединение перед удалением
                if self.graph:
                    self.graph.db.close()
                self.graph = None
                self.db_name = None
                self.prompt = "bel4j> "
            
            Manager.drop(name)
            print(f"База '{name}' удалена.")
                
        except Exception as e:
            print("Ошибка:", e)

    def do_CLOSE(self, _):
        """CLOSE - закрыть текущую базу и вернуться в режим выбора"""
        if self.graph:
            try:
                self.graph.db.close()
                print(f"База '{self.db_name}' закрыта.")
            except Exception as e:
                print(f"Ошибка при закрытии: {e}")
        
        self.graph = None
        self.db_name = None
        self.prompt = "bel4j> "
        print("Выберите другую базу командой USE <name> или создайте новую CREATEDB <name>")

if __name__ == "__main__":
    Bel4jCLI().cmdloop()