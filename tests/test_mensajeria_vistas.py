"""Compatibilidad de las vistas compartidas sin originales operativos."""

import unittest

from app.mensajeria import vistas


class CompatibilidadVistasTest(unittest.TestCase):
    def test_texto_acotado_y_modalidad_solo_visualizar(self):
        for descarga in (False, True):
            self.assertTrue(vistas.compatible(".txt", vistas.LIMITE_TEXTO, descarga))
            self.assertFalse(vistas.compatible(".txt", vistas.LIMITE_TEXTO + 1, descarga))

    def test_originales_de_imagen_exigen_descarga(self):
        for extension in (".png", ".jpg", ".jpeg"):
            self.assertFalse(vistas.compatible(extension, 100, False))
            self.assertTrue(vistas.compatible(extension, 100, True))

    def test_formatos_sin_vista_compatible(self):
        for extension in (".pdf", ".docx", ".xlsx", ".pptx", ".svg", ".html"):
            for descarga in (False, True):
                self.assertFalse(vistas.compatible(extension, 100, descarga))
