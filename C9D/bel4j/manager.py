import os, re
from pathlib import Path
from .core import Graph

DB_DIR = Path.home() / ".bel4j"   # ~/.bel4j/
DB_DIR.mkdir(exist_ok=True)

valid_name = re.compile(r"^\w{1,32}$")

class Manager:
    @staticmethod
    def list_dbs():
        return [p.stem for p in DB_DIR.glob("*.db")]

    @staticmethod
    def exists(name: str) -> bool:
        return (DB_DIR / f"{name}.db").is_file()
    
    @staticmethod
    def get_path(name: str) -> Path:
        """Возвращает путь к файлу базы"""
        return DB_DIR / f"{name}.db"

    @staticmethod
    def create(name: str) -> Graph:
        if not valid_name.fullmatch(name):
            raise ValueError("Имя базы — буквы, цифры, _, длиной 1-32")
        path = DB_DIR / f"{name}.db"
        if path.exists():
            raise FileExistsError("База уже существует")
        return Graph(str(path))

    @staticmethod
    def open(name: str) -> Graph:
        path = DB_DIR / f"{name}.db"
        if not path.exists():
            raise FileNotFoundError("База не найдена")
        return Graph(str(path))
    
    @staticmethod
    def drop(name: str) -> None:
        """Удаляет базу данных"""
        if not valid_name.fullmatch(name):
            raise ValueError("Имя базы — буквы, цифры, _, длиной 1-32")
        path = DB_DIR / f"{name}.db"
        if not path.exists():
            raise FileNotFoundError("База не найдена")
        path.unlink()  