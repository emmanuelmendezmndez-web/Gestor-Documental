"""Pruebas de presentación sin servidor ni base de datos."""
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jinja2 import DictLoader, Environment, select_autoescape


class Enlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.en_categorias = False
        self.enlaces = []
        self.roles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav' and attrs.get('aria-label') == 'Categorías documentales':
            self.en_categorias = True
        if tag == 'a' and self.en_categorias:
            self.enlaces.append(attrs)
        if attrs.get('role') in ('list', 'listitem'):
            self.roles.append(attrs['role'])

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.en_categorias = False


class BibliotecaPresentacionTest(unittest.TestCase):
    def renderizar(self, categoria='Contratos', pagina=3, documentos=None):
        raiz = Path(__file__).resolve().parents[1]
        env = Environment(loader=DictLoader({
            'index.html': (raiz / 'app/templates/index.html').read_text(encoding='utf-8'),
            'base.html': '{% block contenido %}{% endblock %}',
            '_iconos.html': '{% macro icono_archivo(nombre, tamano=20) %}{% endmacro %}',
        }), autoescape=select_autoescape(['html']))
        filtros = {'buscar':'obras & agua', 'categoria':categoria, 'departamento':'Tesorería',
                   'oficio':'OF-1/2025', 'autor':'María', 'desde':'2025-01-01', 'hasta':'2025-12-31', 'orden':'titulo'}
        html = env.get_template('index.html').render(filtros=filtros, categorias=['Contratos', 'Informes'],
            departamentos=['Tesorería'], ordenes=[('titulo','Título')], documentos=documentos or [],
            total=len(documentos or []), total_paginas=3, pagina_actual=pagina, enlace_anterior=None,
            enlace_siguiente=None, avanzada_activa=True, hay_filtros=True, puede=lambda _: False)
        parser = Enlaces(); parser.feed(html)
        return parser, filtros, html

    def test_categoria_conserva_filtros_y_solo_reinicia_pagina_al_cambiar(self):
        parser, filtros, _ = self.renderizar()
        self.assertEqual(len(parser.enlaces), 3)
        for enlace, categoria in zip(parser.enlaces, ['', 'Contratos', 'Informes']):
            valores = parse_qs(urlsplit(enlace['href']).query, keep_blank_values=True)
            for clave, valor in filtros.items():
                if clave != 'categoria': self.assertEqual(valores[clave], [valor])
            self.assertEqual(valores['categoria'], [categoria])
            self.assertEqual(valores.get('p'), ['3'] if categoria == 'Contratos' else None)
        self.assertEqual(parser.enlaces[1]['aria-current'], 'page')

    def test_lista_y_acciones_tienen_semantica_y_nombre(self):
        documento = {'id':1, 'titulo':'Ejemplo ficticio', 'nombre_archivo':'ejemplo.pdf', 'categoria':'Contratos',
                     'numero_oficio':'', 'departamento':'', 'fecha_efectiva':'2025-01-01', 'fecha_documento':'2025-01-01'}
        parser, _, html = self.renderizar(documentos=[documento])
        self.assertEqual(parser.roles, ['list', 'listitem'])
        self.assertIn('aria-label="Ver ficha de Ejemplo ficticio"', html)
        self.assertIn('Categoría: </span>Contratos', html)
        self.assertIn('Fecha: </span>2025-01-01', html)


if __name__ == '__main__':
    unittest.main()
