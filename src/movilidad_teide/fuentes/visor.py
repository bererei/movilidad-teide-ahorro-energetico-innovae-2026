"""Lectores de visor; conservo formatos, ausencias y procedencia."""
import ast
import re
from html.parser import HTMLParser
from pathlib import Path

class Documento(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = {'tag': 'root', 'attrs': {}, 'children': []}
        self.pila = [self.raiz]

    def handle_starttag(self, tag, attrs):
        nodo = {'tag': tag, 'attrs': dict(attrs), 'children': []}
        self.pila[-1]['children'].append(nodo)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.pila.append(nodo)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.pila) - 1, 0, -1):
            if self.pila[i]['tag'] == tag:
                del self.pila[i:]
                break

    def handle_data(self, data):
        self.pila[-1]['children'].append(data)

def recorrer(nodo):
    yield nodo
    for hijo in nodo['children']:
        if isinstance(hijo, dict):
            yield from recorrer(hijo)

def texto(nodo):
    if isinstance(nodo, str):
        return nodo
    if nodo['tag'] in {'script', 'style'}:
        return ''
    return ' '.join((texto(hijo) for hijo in nodo['children']))

def constante_literal(nombre, *, codigo):
    patron = 'const ' + re.escape(nombre) + ' = (\\{.*?\\n  \\});'
    coincidencia = re.search(patron, codigo, flags=re.S)
    if not coincidencia:
        raise ValueError('No encuentro la constante publicada: ' + nombre)
    literal = re.sub('([\\{,]\\s*)([A-Za-z_$][\\w$]*)(\\s*:)', "\\1'\\2'\\3", coincidencia.group(1))
    return ast.literal_eval(literal)
