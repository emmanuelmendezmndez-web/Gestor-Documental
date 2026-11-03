"""Comprobaciones de contratos usados por rutas y mensajes."""

import ast
from pathlib import Path
import re
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.mensajes import AVISOS
from app.seleccion import leer_seleccion
from app.seguridad import PERMISOS, requiere_permiso
from app.rutas_cuenta import AVISOS_CUENTA
from app.rutas_usuarios import AVISOS_USUARIOS
from app import previsualizacion
from app.actividad import ACCIONES


class ContratosTest(unittest.TestCase):
    def test_permisos_de_todos_los_modulos(self):
        raiz = Path(__file__).resolve().parents[1] / "app"
        conocidos = set().union(*PERMISOS.values())
        encontrados = []
        for archivo in raiz.rglob("*.py"):
            for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id in {"requiere_permiso", "transaccion_documental"}:
                    posicion = 0 if nodo.func.id == "requiere_permiso" else 1
                    self.assertTrue(len(nodo.args) > posicion and isinstance(nodo.args[posicion], ast.Constant)
                                    and isinstance(nodo.args[posicion].value, str),
                                    f"Permiso no literal en {archivo}:{nodo.lineno}")
                    permiso = nodo.args[posicion].value
                    encontrados.append(permiso)
                    self.assertIn(permiso, conocidos, f"Permiso desconocido en {archivo}:{nodo.lineno}")
        self.assertTrue(encontrados, "No se encontraron permisos para comprobar")

    def test_avisos_de_redirecciones_y_catalogos_propios(self):
        raiz = Path(__file__).resolve().parents[1] / "app"
        for archivo in raiz.rglob("*.py"):
            arbol = ast.parse(archivo.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                    for codigo in re.findall(r"[?&]aviso=([a-z_]+)", nodo.value):
                        self.assertIn(codigo, AVISOS, f"{archivo}:{nodo.lineno}")
                if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Name):
                    continue
                nombre = nodo.func.id
                indice = None
                catalogo = AVISOS
                if archivo.name == "rutas_cuenta.py" and nombre == "redirigir":
                    indice, catalogo = 0, AVISOS_CUENTA
                elif archivo.name == "rutas_usuarios.py" and nombre == "redirigir":
                    indice, catalogo = 1, AVISOS_USUARIOS
                elif nombre in {"avisar", "fallo_subida", "avisar_edicion", "avisar_eliminacion"}:
                    indice = {"avisar": 0, "fallo_subida": 1, "avisar_edicion": 1, "avisar_eliminacion": 1}[nombre]
                if indice is not None and len(nodo.args) > indice:
                    argumento = nodo.args[indice]
                    candidatos = [argumento.body, argumento.orelse] if isinstance(argumento, ast.IfExp) else [argumento]
                    for candidato in candidatos:
                        if isinstance(candidato, ast.Constant) and isinstance(candidato.value, str):
                            self.assertIn(candidato.value, catalogo, f"{archivo}:{nodo.lineno}")

    def test_configuracion_con_directorio_de_datos_alternativo(self):
        with tempfile.TemporaryDirectory() as temporal:
            entorno = os.environ.copy()
            entorno["GESTOR_DATA_DIR"] = temporal
            entorno["GESTOR_SECRET_KEY"] = "clave-ficticia-de-prueba"
            codigo = '''
from pathlib import Path
from app import configuracion as c, database, main, seguridad, rutas_cuenta, respaldo, previsualizacion
assert c.DB_PATH == database.DB_PATH == Path(__import__("os").environ["GESTOR_DATA_DIR"]).resolve() / "gestor.db"
assert main.STORAGE_DIR == respaldo.STORAGE_DIR == c.STORAGE_DIR
assert rutas_cuenta.FOTOS_PERFIL_DIR == c.FOTOS_PERFIL_DIR
assert main.AVISOS_DIR == c.AVISOS_DIR
assert seguridad.SECRET_PATH == respaldo.SECRET_PATH == c.SECRET_PATH
assert previsualizacion.DIRECTORIO_CACHE == c.DIRECTORIO_CACHE
'''
            subprocess.run([sys.executable, "-c", codigo], env=entorno, check=True, timeout=30)

    def test_codigos_generados_por_validaciones(self):
        raiz = Path(__file__).resolve().parents[1] / "app"
        for archivo, funcion, catalogo in (
            ("metadatos.py", "limpiar_metadatos", AVISOS),
            ("seleccion.py", "leer_seleccion", AVISOS),
            ("rutas_usuarios.py", "validar_password", AVISOS_USUARIOS),
        ):
            arbol = ast.parse((raiz / archivo).read_text(encoding="utf-8"))
            nodo_funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == funcion)
            for nodo in ast.walk(nodo_funcion):
                if isinstance(nodo, ast.Return):
                    valor = nodo.value.elts[-1] if isinstance(nodo.value, ast.Tuple) else nodo.value
                    if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
                        self.assertIn(valor.value, catalogo, f"{archivo}:{nodo.lineno}")
        arbol = ast.parse((raiz / "archivos.py").read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "ArchivoInvalido":
                if nodo.args and isinstance(nodo.args[0], ast.Constant):
                    self.assertIn(nodo.args[0].value, AVISOS)

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
