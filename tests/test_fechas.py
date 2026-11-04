"""El filtro de fechas conserva el mismo resultado en ambas pantallas."""

import unittest

from app.rutas_actividad import fecha_valida as fecha_actividad
from app.utilidades import fecha_valida


class FechasTest(unittest.TestCase):
    def test_fechas_validas_e_invalidas(self):
        casos = {
            "2024-02-29": "2024-02-29",
            "20240229": "2024-02-29",
            "2023-02-29": "",
            "2026-13-01": "",
            "": "",
            "texto": "",
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(fecha_valida(entrada), esperado)
                self.assertEqual(fecha_actividad(entrada), esperado)
