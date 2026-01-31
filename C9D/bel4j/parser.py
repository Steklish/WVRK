from lark import Lark
from pathlib import Path

grammar = Path(__file__).with_name("cypher.lark").read_text(encoding='utf-8')
parser = Lark(grammar, parser="lalr", cache = False)