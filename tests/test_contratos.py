"""Comprobaciones de contratos usados por rutas y mensajes."""

import ast
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from app.mensajes import AVISOS
from app.seleccion import leer_seleccion
from app.seguridad import requiere_permiso
from app import previsualizacion
from app.actividad import ACCIONES


class ContratosTest(unittest.TestCase):
    def test_permiso_inexistente_falla_al_declarar_ruta(self):
        with self.assertRaises(ValueError):
            requiere_permiso("permiso_que_no_existe")
        self.assertTrue(callable(requiere_permiso("ver")))

    def test_seleccion(self):
        self.assertEqual(leer_seleccion([])[2], "seleccion_vacia")
        self.assertEqual(leer_seleccion(list(range(201)))[2], "seleccion_exceso")
        self.assertEqual(leer_seleccion([3, 3, 2]), ([3, 2], "?,?", None))
        self.assertIsNone(leer_seleccion(list(range(200)))[2])

    def test_avisos_literal_en_main_existen(self):
        # Las rutas de cuenta y usuarios usan catálogos propios, no AVISOS.
        raiz = Path(__file__).resolve().parents[1]
        arbol = ast.parse((raiz / "app" / "main.py").read_text(encoding="utf-8"))
        codigos = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                codigos.update(re.findall(r"[?&]aviso=([a-z_]+)", nodo.value))
        self.assertFalse(codigos - AVISOS.keys(), f"Avisos desconocidos: {codigos - AVISOS.keys()}")

        arbol = ast.parse((raiz / "app" / "servicios" / "avisos.py").read_text(encoding="utf-8"))
        codigos_servicio = {
            nodo.value.value for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Return) and isinstance(nodo.value, ast.Constant)
            and isinstance(nodo.value.value, str)
        }
        self.assertFalse(codigos_servicio - AVISOS.keys())

    def test_auditoria_conserva_accion_historica(self):
        self.assertIn("eliminar", ACCIONES)
        self.assertIn("papelera_enviar", ACCIONES)
        self.assertIn("eliminar_definitivo", ACCIONES)

    def test_vista_office_reutiliza_cache_y_detecta_cambio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ejecutable = base / "soffice.exe"
            ejecutable.write_bytes(b"ejecutable ficticio")
            origen = base / "documento.docx"
            origen.write_bytes(b"version uno")

            def convertir(comando, **kwargs):
                destino = Path(comando[comando.index("--outdir") + 1])
                (destino / "documento.pdf").write_bytes(b"%PDF-ficticio")
                return type("Resultado", (), {"returncode": 0})()

            with patch.object(previsualizacion, "DIRECTORIO_CACHE", base / "cache"), \
                 patch.object(previsualizacion, "localizar_libreoffice", return_value=str(ejecutable)), \
                 patch.object(previsualizacion.subprocess, "run", side_effect=convertir) as llamada:
                primero, _ = previsualizacion.convertir_office_a_pdf(origen)
                segundo, _ = previsualizacion.convertir_office_a_pdf(origen)
                self.assertEqual(primero, segundo)
                self.assertEqual(llamada.call_count, 1)
                origen.write_bytes(b"version dos")
                tercero, _ = previsualizacion.convertir_office_a_pdf(origen)
                self.assertNotEqual(primero, tercero)
                self.assertEqual(llamada.call_count, 2)


if __name__ == "__main__":
    unittest.main()
